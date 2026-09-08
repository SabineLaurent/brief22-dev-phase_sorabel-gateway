"""Reranking : une interface, deux implémentations commutables.

Même schéma que ``retrieval/embedder.py`` — le choix se fait par configuration, jamais par
le code appelant : si les **trois** variables ``AZURE_RERANK_*`` sont renseignées, le rerank
part sur le déploiement Cohere d'Azure AI Foundry ; sinon sur le cross-encoder local
``cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`` — mMARCO parce que le corpus est en français,
pas ``ms-marco-MiniLM`` (``Q3`` §6).

**La règle est tout ou rien**, et le repli est le local : un reranker à moitié configuré doit
retomber sur un défaut qui marche, jamais échouer à la première question. Une configuration
partielle est signalée sur ``stderr`` — silencieuse, elle ferait croire à un rerank de service
là où le cross-encoder travaille.

Le score rendu est **toujours borné dans ``[0, 1]``** : c'est la condition posée par
``Q4`` §3 pour qu'un seuil de refus soit une opération sensée sur cette échelle. Les
cross-encoders mMARCO ne sont pas tous nativement dans cet intervalle — une sigmoïde
l'y ramène ; Cohere rend nativement un ``relevance_score`` dans cet intervalle.

.. warning::

   **Le seuil de refus est solidaire du reranker qui l'a produit.** ``RERANK_THRESHOLD``
   (0,0530) est calibré pour le cross-encoder local, et rien dans le code ne relie l'un à
   l'autre : changer de reranker sans ``make calibrer-hybride`` règle le refus sur une
   distribution de scores qui n'est pas la sienne, en silence. Constat de revue ouvert.
"""

from __future__ import annotations

import math
import sys
from functools import lru_cache
from typing import Any, Protocol, cast

import httpx

from config import Settings
from config import settings as default_settings

#: Délai d'un appel de rerank. Un seul appel par question, sur 20 candidats.
_HTTP_TIMEOUT = 30.0


class Reranker(Protocol):
    """Ce que la gateway attend d'un fournisseur de rerank."""

    name: str

    def score(self, query: str, documents: list[str]) -> list[float]:
        """Note chaque document pour la requête. Rend une liste bornée ``[0, 1]``,
        dans l'ordre d'entrée."""


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


class LocalReranker:
    """Cross-encoder local, chargé paresseusement — même motif que ``LocalEmbedder``."""

    def __init__(self, model_name: str) -> None:
        self.name = model_name
        self._model = None

    def _load_model(self):  # type: ignore[no-untyped-def]
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.name)
        return self._model

    def score(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        pairs = [(query, document) for document in documents]
        logits = self._load_model().predict(pairs)
        return [_sigmoid(float(logit)) for logit in logits]


class CohereReranker:
    """Reranker Cohere déployé sur Azure AI Foundry — un vrai reranker, pas un chat détourné.

    Son API n'est **pas** OpenAI-compatible, contrairement à l'inférence de chat et aux
    embeddings — un rerank n'a pas d'équivalent dans l'API OpenAI. Il ne partage donc rien
    avec ``azure_client.py`` : ni le client, ni l'endpoint, ni la clé.

    ``azure_rerank_endpoint`` est **l'URL complète de l'appel**, pas une base : Azure AI
    Foundry sert les modèles partenaires sous ``services.ai.azure.com/providers/<nom>/…``,
    et le chemin dépend du fournisseur. Le composer ici lierait ce module à Cohere ; le
    lire tel quel le rend indifférent au fournisseur. L'URL se trouve dans le **détail** du
    déploiement, pas dans le champ « point de terminaison » du panneau, qui affiche
    l'endpoint générique de la ressource.

    Deux détails du contrat, qui sont la raison d'être de cette classe :

    * la réponse est **triée par pertinence**, chaque résultat portant son ``index`` d'entrée.
      Le protocole :class:`Reranker` exige l'ordre d'entrée — c'est ici qu'on le rétablit ;
    * ``top_n`` vaut le nombre de documents. Demander moins ferait taire les scores des
      derniers, qui vaudraient alors 0 sans que rien ne le dise — or c'est le score du
      **premier** qui sert de critère de refus, et il se calcule par comparaison.
    """

    def __init__(self, endpoint: str, api_key: str, deployment: str) -> None:
        self.name = deployment
        self._endpoint = endpoint.rstrip("/")   # l'URL de rerank, telle quelle
        self._api_key = api_key
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        """Client persistant : un appel par question, mais la poignée TLS se paierait à
        chaque fois. Construit ici plutôt qu'au ``__init__`` pour que l'objet reste
        inoffensif tant qu'aucune recherche n'a lieu."""
        if self._client is None:
            self._client = httpx.Client(
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=_HTTP_TIMEOUT,
            )
        return self._client

    def score(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        response = self._get_client().post(
            self._endpoint,
            json={
                "model": self.name,
                "query": query,
                "documents": documents,
                "top_n": len(documents),
            },
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        by_index = {
            int(item["index"]): float(item["relevance_score"])
            for item in payload.get("results", [])
        }
        return [max(0.0, min(1.0, by_index.get(i, 0.0))) for i in range(len(documents))]


@lru_cache(maxsize=None)
def _reranker(cohere: bool, endpoint: str, api_key: str, deployment: str,
              model: str) -> Reranker:
    """Le cache est ici, sur les seuls champs lus — ``Settings`` n'est pas hachable."""
    if cohere:
        return cast(Reranker, CohereReranker(endpoint, api_key, deployment))
    return cast(Reranker, LocalReranker(model))


@lru_cache(maxsize=None)
def _warn_partial(deployment: str, endpoint: str, api_key: str) -> None:
    """Une seule fois par configuration : le repli est voulu, le silence ne l'est pas."""
    posees = [
        nom
        for nom, valeur in (
            ("AZURE_RERANK_DEPLOYMENT", deployment),
            ("AZURE_RERANK_ENDPOINT", endpoint),
            ("AZURE_RERANK_API_KEY", api_key),
        )
        if valeur
    ]
    if posees and len(posees) < 3:
        print(
            f"rerank : configuration Azure partielle ({', '.join(posees)} renseignée(s) "
            "sur trois) — repli sur le cross-encoder local. Les trois sont nécessaires.",
            file=sys.stderr,
        )


def build_reranker(settings: Settings | None = None) -> Reranker:
    """Rend le reranker configuré. Cohere si les **trois** variables le sont, local sinon.

    Mémoïsé pour la même raison que :func:`build_embedder` : ``LocalReranker`` charge son
    ``CrossEncoder`` par instance, et ``search()`` en construisait un par appel.
    """
    settings = settings or default_settings
    _warn_partial(
        settings.azure_rerank_deployment,
        settings.azure_rerank_endpoint,
        settings.azure_rerank_api_key,
    )
    return _reranker(
        settings.uses_azure_rerank,
        settings.azure_rerank_endpoint,
        settings.azure_rerank_api_key,
        settings.azure_rerank_deployment,
        settings.reranker_model,
    )
