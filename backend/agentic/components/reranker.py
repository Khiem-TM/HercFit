"""Existing lexical/topic and publisher-quality ranking for public search results."""
import re
from models.foods import normalize_food_text
from research.sources import TIER_RANK, rate

GENERIC_WORDS=frozenset({'bao','nhieu','calo','kcal','calories','calorie','nutrition','dinh','duong','thanh','phan','cach','lam',
                         'la','gi','co','cua','va','cho','mot','ly','coc','size','the','and','of','facts'})


def target_words(target):
    return {w for w in re.findall(r'\w+',normalize_food_text(target)) if len(w)>1 and w not in GENERIC_WORDS}


def relevance(target,text):
    """Share of the researched item's words that a page mentions (accent-insensitive)."""
    words=target_words(target)
    if not words: return 0.0
    page=set(re.findall(r'\w+',normalize_food_text(text)))
    return len(words & page)/len(words)


TOPIC_TERMS={'foods':re.compile(r'kcal|calo|calori|nutrition|dinh duong|nang luong|protein|dam|carb|chat beo|\bfat\b|chat xo'),
             'exercises':re.compile(r'\bmet\b|calo|muscle|nhom co|co bap|ky thuat|technique|how to|huong dan')}


NUTRITION_FIELDS=frozenset({'energy_kcal','protein_g','carbohydrate_g','fat_g','fiber_g','serving_size','portions','portion_weight_g'})


def topical(domain,text):
    pattern=TOPIC_TERMS.get(domain)
    return bool(pattern and pattern.search(normalize_food_text(text)))


def rank_sources(rows, target, *, domain=None, product=None, limit=6):
    def rank(row):
        text = row.get('title', '') + ' ' + row.get('content', '')
        score = relevance(target, text) + (.5 if domain and topical(domain, text) else 0)
        return (-round(score, 1), TIER_RANK[rate(row['url'], row['url'], product).tier])
    return sorted({row['url']: row for row in rows}.values(), key=rank)[:limit]
