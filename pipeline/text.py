"""
Traitements de texte : nettoyage, mots vides, sentiment par lexique.
"""
import re

# Mots vides français (liste fixe, pour ne dépendre d'aucun téléchargement NLTK)
FRENCH_STOPWORDS = {
    'au', 'aux', 'avec', 'ce', 'ces', 'dans', 'de', 'des', 'du', 'elle',
    'en', 'et', 'eux', 'il', 'je', 'la', 'le', 'leur', 'lui', 'ma',
    'mais', 'me', 'même', 'mes', 'moi', 'mon', 'ne', 'nos', 'notre',
    'nous', 'on', 'ou', 'par', 'pas', 'pour', 'qu', 'que', 'qui', 'sa',
    'se', 'ses', 'son', 'sur', 'ta', 'te', 'tes', 'toi', 'ton', 'tu',
    'un', 'une', 'vos', 'votre', 'vous', 'c', 'd', 'j', 'l', 'à', 'm',
    'n', 's', 't', 'y', 'été', 'étée', 'étées', 'étés', 'étant', 'suis',
    'es', 'est', 'sommes', 'êtes', 'sont', 'serai', 'seras', 'sera',
    'serons', 'serez', 'seront', 'serais', 'serait', 'serions', 'seriez',
    'seraient', 'étais', 'était', 'étions', 'étiez', 'étaient', 'fus',
    'fut', 'fûmes', 'fûtes', 'furent', 'sois', 'soit', 'soyons', 'soyez',
    'soient', 'fusse', 'fusses', 'fût', 'fussions', 'fussiez', 'fussent',
    'ayant', 'eu', 'eue', 'eues', 'eus', 'ai', 'as', 'avons', 'avez',
    'ont', 'aurai', 'auras', 'aura', 'aurons', 'aurez', 'auront',
    'aurais', 'aurait', 'aurions', 'auriez', 'auraient', 'avais',
    'avait', 'avions', 'aviez', 'avaient', 'eut', 'eûmes', 'eûtes',
    'eurent', 'aie', 'aies', 'ait', 'ayons', 'ayez', 'aient', 'eusse',
    'eusses', 'eût', 'eussions', 'eussiez', 'eussent', 'ceci', 'cela',
    'celà', 'cet', 'cette', 'ici', 'ils', 'les', 'leurs', 'quel',
    'quels', 'quelle', 'quelles', 'sans', 'soi', 'tout', 'tous', 'toute',
    'toutes', 'très', 'trois', 'trop'
}

# Mots présents dans presque tous les commentaires : ils ne distinguent aucun thème
DOMAIN_STOPWORDS = {"formation", "formations", "formateur", "cette", "mon", "ma", "mes",
                    "très", "un", "peu", "mais", "bien", "plus"}

# Identifiants de formateurs cités dans les commentaires (« le formateur FOR35 a... »)
TRAINER_ID_PATTERN = re.compile(r"\bfor\d+\b", re.IGNORECASE)


def clean_text(text):
    """Minuscules, sans identifiants de formateurs ni ponctuation (accents conservés)"""
    if not isinstance(text, str):
        return ""
    text = TRAINER_ID_PATTERN.sub(" ", text.lower())
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Lexique de sentiment. Les mots de 5 lettres ou plus valent aussi comme racine
# (« recommand » couvre « recommande », « recommanderais »...) ; les mots courts
# doivent correspondre exactement, pour que « bon » ne compte pas dans « bonjour ».
POSITIVE_WORDS = ['excellent', 'super', 'bien', 'bon', 'bonne', 'agréable', 'utile',
                  'intéress', 'formidable', 'parfait', 'génial', 'efficace',
                  'clair', 'pratique', 'enrichiss', 'motiv', 'satisfait',
                  'content', 'ravi', 'recommand', 'appréci', 'fantastique']

NEGATIVE_WORDS = ['mauvais', 'nul', 'nulle', 'décevant', 'difficile', 'compliqué',
                  'inutile', 'ennuyeux', 'pénible', 'médiocre', 'faible',
                  'confus', 'incompréhensible', 'lent', 'lente', 'problème', 'déçu',
                  'insatisfait', 'trop', 'cher', 'manque']

# Mots qui inversent le sens des 2 mots suivants (« pas utile », « peu clair »)
NEGATORS = {'pas', 'ne', 'n', 'jamais', 'aucun', 'aucune', 'sans', 'peu', 'guère'}


def _matches(token, lexicon):
    return any(token == w or (len(w) >= 5 and token.startswith(w)) for w in lexicon)


def sentiment_label(text):
    """
    Sentiment par lexique : mots positifs contre mots négatifs, inversés après une
    négation. Méthode de référence simple et explicable, pas un modèle appris.
    """
    tokens = re.findall(r"\w+", str(text).lower())
    pos_count = neg_count = 0
    for i, token in enumerate(tokens):
        is_pos, is_neg = _matches(token, POSITIVE_WORDS), _matches(token, NEGATIVE_WORDS)
        if not (is_pos or is_neg):
            continue
        negated = any(t in NEGATORS for t in tokens[max(0, i - 2):i])
        if is_pos != negated:
            pos_count += 1
        else:
            neg_count += 1

    if pos_count > neg_count:
        return "Positif"
    if neg_count > pos_count:
        return "Négatif"
    return "Neutre"
