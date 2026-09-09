// Les quatre profils côte à côte, sur une seule question.
//
// Ce composant n'interprète rien : il affiche ce que `app_compare.py` lui passe. La
// couleur d'une colonne vient du `statut` calculé côté Python — c'est-à-dire du contrat
// servi par le serveur MCP, pas d'une règle réécrite ici. Deux tables de correspondance
// (une par côté) auraient fini par diverger, et c'est justement la divergence que cette
// interface sert à rendre visible.
//
// `props` et `updateElement` sont injectés par Chainlit ; le fichier est chargé tel quel
// par le navigateur depuis /public/elements/Comparaison.jsx et transpilé côté client.
import { Badge } from "@/components/ui/badge";
// `@/components/markdown` et non `react-markdown` : les custom elements n'ont accès
// qu'aux modules que Chainlit expose à son `require`, et celui-ci n'y est pas. Celui
// de Chainlit y est, et il rend le texte exactement comme une bulle de chat — même
// coloration de code, mêmes liens.
import { Markdown } from "@/components/markdown";

// Les cinq statuts du contrat DSI, plus trois que le protocole ne connaît pas : `sans_reponse`,
// que le client pose quand le modèle déclare ne pas pouvoir répondre, et les deux états de
// l'interface — l'attente, et le fait qu'aucun tool n'ait été appelé.
//
// `sans_reponse` prend l'ambre de `hors_corpus`, et c'est délibéré : les deux disent « rien
// n'a été obtenu », là où le rouge dit « la gateway a refusé ». Ce sont bien deux familles,
// et le libellé, lui, les sépare.
const COULEURS = {
  en_cours: "#94a3b8",
  aucun_appel: "#64748b",
  ok: "#16a34a",
  clarification: "#2563eb",
  hors_corpus: "#d97706",
  sans_reponse: "#d97706",
  refused: "#dc2626",
  error: "#b91c1c",
};

const LIBELLES = {
  en_cours: "en cours…",
  aucun_appel: "aucun tool appelé",
  ok: "servi",
  clarification: "clarification demandée",
  hors_corpus: "hors corpus",
  sans_reponse: "sans réponse",
  refused: "refusé",
  error: "erreur",
};

// Le seul CSS du composant, et il n'y est que pour les tableaux.
//
// `overflow-x: auto` sur le corps de colonne ne suffisait pas : la classe `prose` de
// Chainlit laisse un tableau se **comprimer** jusqu'à écrire ses en-têtes une lettre par
// ligne (« E n t r e p ô t ») plutôt que de déborder. Ce qui déclenche le débordement,
// donc le défilement, c'est `white-space: nowrap` sur les cellules — sans lui, rien ne
// dépasse jamais et il n'y a rien à faire défiler.
//
// Il faut du CSS et non un style en ligne : le tableau est produit par le composant
// Markdown de Chainlit, aucune prop de ce fichier ne l'atteint.
const STYLE_TABLEAUX = `
.sorabel-corps table { display: block; width: max-content; max-width: none;
                       overflow-x: auto; border-collapse: collapse; margin: 0.4rem 0;
                       font-size: 0.78em; }
.sorabel-corps th, .sorabel-corps td { white-space: nowrap; padding: 0.2rem 0.45rem;
                                       border: 1px solid rgba(128,128,128,0.28); }
.sorabel-corps th { font-weight: 600; text-align: left; }
.sorabel-corps pre, .sorabel-corps code { white-space: pre; }
.sorabel-corps p:first-child { margin-top: 0; }
`;

function Points() {
  // Trois barres grises plutôt qu'un spinner : la colonne garde sa hauteur pendant
  // l'attente, donc la grille ne saute pas quand la première réponse arrive.
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
      {[100, 85, 60].map((largeur) => (
        <div
          key={largeur}
          style={{
            width: `${largeur}%`,
            height: "0.7rem",
            borderRadius: "0.25rem",
            background: "currentColor",
            opacity: 0.12,
          }}
        />
      ))}
    </div>
  );
}

function Colonne({ colonne }) {
  const couleur = COULEURS[colonne.statut] || COULEURS.en_cours;
  const attente = colonne.statut === "en_cours";
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        minWidth: 0,
        border: "1px solid",
        borderColor: "rgba(128,128,128,0.25)",
        borderTop: `3px solid ${couleur}`,
        borderRadius: "0.5rem",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "0.6rem 0.7rem",
          borderBottom: "1px solid rgba(128,128,128,0.2)",
          display: "flex",
          flexDirection: "column",
          gap: "0.35rem",
        }}
      >
        <div style={{ fontWeight: 600, fontSize: "0.95rem" }}>{colonne.libelle}</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem" }}>
          <Badge variant="outline" style={{ fontFamily: "monospace" }}>
            {colonne.profil}
          </Badge>
          {colonne.tools === null ? null : (
            <Badge variant="secondary">
              {colonne.tools.length} tool{colonne.tools.length > 1 ? "s" : ""}
            </Badge>
          )}
        </div>
        <div style={{ fontSize: "0.75rem", color: couleur, fontWeight: 500 }}>
          {LIBELLES[colonne.statut] || colonne.statut}
        </div>
      </div>

      <div
        className="sorabel-corps"
        style={{
          padding: "0.7rem",
          fontSize: "0.85rem",
          lineHeight: 1.5,
          flexGrow: 1,
          minWidth: 0,
          wordBreak: "break-word",
        }}
      >
        {attente ? <Points /> : <Markdown>{colonne.reponse}</Markdown>}
      </div>

      {colonne.calls && colonne.calls.length > 0 && (
        <div
          style={{
            padding: "0.5rem 0.7rem",
            borderTop: "1px solid rgba(128,128,128,0.2)",
            display: "flex",
            flexWrap: "wrap",
            gap: "0.3rem",
          }}
        >
          {colonne.calls.map((appel, rang) => (
            <Badge
              key={`${appel.tool}-${rang}`}
              variant="outline"
              style={{
                fontFamily: "monospace",
                fontSize: "0.68rem",
                borderColor: COULEURS[appel.statut] || COULEURS.en_cours,
                color: COULEURS[appel.statut] || COULEURS.en_cours,
              }}
              title={`statut ${appel.statut}`}
            >
              {appel.tool} · {appel.code}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Comparaison() {
  const colonnes = props.colonnes || [];
  return (
    <div style={{ width: "100%" }}>
      <style>{STYLE_TABLEAUX}</style>
      {props.question && (
        <div
          style={{
            marginBottom: "0.6rem",
            fontSize: "0.85rem",
            opacity: 0.7,
            fontStyle: "italic",
          }}
        >
          {props.question}
        </div>
      )}
      <div
        style={{
          display: "grid",
          // Ni nombre de colonnes figé, ni pixel — `auto-fit` + `min()`, la forme qui se
          // passe de media query (indisponible dans un style en ligne) :
          //
          // * `auto-fit` place autant de colonnes que la largeur en autorise et **replie**
          //   les autres à la ligne. `repeat(4, …)` les gardait sur une seule ligne quoi
          //   qu'il arrive, et la quatrième sortait du cadre ;
          // * `13rem` et non `208px` : le plancher suit la taille de police du lecteur,
          //   donc un réglage d'accessibilité élargit les colonnes au lieu de tasser
          //   davantage de texte dedans ;
          // * `min(100%, …)` est ce qui rend le plancher inoffensif sur téléphone : sous
          //   13rem de large, le plancher devient 100 % et les colonnes s'empilent au lieu
          //   de déborder.
          //
          // Le repère mesuré reste utile pour choisir 13rem : Chainlit borne un message à
          // 700 px, 892 avec le `layout = "wide"` de `compare_root/.chainlit/config.toml`
          // (relevé au navigateur, viewport 1600). Vérifié à trois largeurs : 4 colonnes à
          // 1600, 3 puis 1 à 900, empilées à 420 — et `scrollWidth == clientWidth` dans les
          // trois cas, donc rien n'est jamais coupé.
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 13rem), 1fr))",
          gap: "0.6rem",
          alignItems: "stretch",
        }}
      >
        {colonnes.map((colonne) => (
          <Colonne key={colonne.role} colonne={colonne} />
        ))}
      </div>
    </div>
  );
}
