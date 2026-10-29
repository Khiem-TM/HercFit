"""Code-owned source registry: a source's authority comes from its publisher, never from a model label.

Tiers: primary (public health agencies, national nutrition databases, the Compendium of
Physical Activities), professional (professional bodies, hospitals, universities and the
operator-curated knowledge base), secondary (reputable health media and references).
Everything else is 'unknown': usable as supporting text, never counted by the quality gate.

Scopes restrict which fields a source may support. MET values affect calorie estimates,
so only sources with the 'met' scope can back configuration.default_met.
"""
from dataclasses import dataclass
from urllib.parse import urlparse

from models.foods import normalize_food_text

TIER_RANK = {'primary': 0, 'professional': 1, 'secondary': 2, 'unknown': 3}
ALL = frozenset({'nutrition', 'exercise', 'qa'})

# Matched on the hostname or any parent domain ("fdc.nal.usda.gov" matches "usda.gov").
REGISTRY = {
    # Energy cost of physical activity
    'pacompendium.com': ('primary', ALL | {'met'}),
    'compendiumofphysicalactivities.org': ('primary', ALL | {'met'}),
    'acsm.org': ('professional', ALL | {'met'}),
    # Public health agencies and national databases
    'who.int': ('primary', ALL | {'met'}),
    'cdc.gov': ('primary', ALL | {'met'}),
    'nih.gov': ('primary', ALL | {'met'}),
    'health.gov': ('primary', ALL),
    'nhs.uk': ('primary', ALL),
    'usda.gov': ('primary', ALL),
    'fao.org': ('primary', ALL),
    'efsa.europa.eu': ('primary', ALL),
    'moh.gov.vn': ('primary', ALL),
    'viendinhduong.vn': ('primary', ALL),
    'nin.gov.vn': ('primary', ALL),
    # Professional bodies, hospitals and universities
    'nsca.com': ('professional', ALL),
    'acefitness.org': ('professional', ALL),
    'eatright.org': ('professional', ALL),
    'heart.org': ('professional', ALL),
    'mayoclinic.org': ('professional', ALL),
    'clevelandclinic.org': ('professional', ALL),
    'hopkinsmedicine.org': ('professional', ALL),
    'harvard.edu': ('professional', ALL),
    'vinmec.com': ('professional', ALL),
    'tamanhhospital.vn': ('professional', ALL),
    'medlatec.vn': ('professional', ALL),
    # Reputable references and health media
    'exrx.net': ('secondary', ALL),
    'healthline.com': ('secondary', ALL),
    'verywellfit.com': ('secondary', ALL),
    'verywellhealth.com': ('secondary', ALL),
    'medicalnewstoday.com': ('secondary', ALL),
    'webmd.com': ('secondary', ALL),
    'nutritionix.com': ('secondary', ALL),
    'wikipedia.org': ('secondary', ALL),
    'hellobacsi.com': ('secondary', ALL),
    'suckhoedoisong.vn': ('secondary', ALL),
    # Major Vietnamese newspapers (health sections quote clinicians and nutrition institutes)
    'tuoitre.vn': ('secondary', ALL),
    'thanhnien.vn': ('secondary', ALL),
    'vnexpress.net': ('secondary', ALL),
    'dantri.com.vn': ('secondary', ALL),
    'vietnamnet.vn': ('secondary', ALL),
    'nld.com.vn': ('secondary', ALL),
    'laodong.vn': ('secondary', ALL),
}
# Social platforms: posts are opinions and pages usually block extraction; never rated,
# only shown to the user as unverified estimates.
SOCIAL = frozenset({'tiktok.com', 'facebook.com', 'threads.com', 'threads.net', 'instagram.com', 'youtube.com',
                    'x.com', 'twitter.com', 'reddit.com'})
# Government and academic hosts that are not listed individually.
SUFFIXES = {'.gov': ('professional', ALL), '.gov.vn': ('professional', ALL), '.edu': ('professional', ALL),
            '.edu.vn': ('professional', ALL)}
KNOWLEDGE_BASE = ('professional', ALL)
# Platforms that host many brands are never "the manufacturer".
PLATFORMS = frozenset({'google', 'facebook', 'youtube', 'tiktok', 'instagram', 'shopee', 'lazada', 'tiki', 'grab',
                       'foody', 'baemin', 'wikipedia', 'amazon', 'reddit', 'pinterest'})


def _brand(host):
    labels = host.split('.')[:-1]
    if len(labels) > 1 and labels[-1] in {'com', 'net', 'org', 'co', 'edu', 'gov'}:
        labels = labels[:-1]
    return labels[-1] if labels else ''


def manufacturer(host, product):
    """A brand's own site (katinat.vn for "trà sữa Katinat") is the primary source of its product label."""
    brand = _brand(host)
    return (len(brand) >= 4 and brand not in PLATFORMS and bool(product)
            and brand in normalize_food_text(product).replace(' ', ''))


@dataclass(frozen=True)
class Rating:
    tier: str
    scopes: frozenset = frozenset()
    publisher: str | None = None


def rate(source_id, url='', product=None):
    """Rating of one evidence source. Knowledge-base passages ('kb:' ids) are operator-curated;
    their original URL, when known, can still grant a narrower registry scope such as MET.
    `product` (a researched food's name) lets the brand's own site rate as its label."""
    host = (urlparse(url or (source_id if '://' in (source_id or '') else '')).hostname or '').lower().removeprefix('www.')
    if host:
        parts = host.split('.')
        for index in range(len(parts) - 1):
            domain = '.'.join(parts[index:])
            if domain in REGISTRY:
                tier, scopes = REGISTRY[domain]
                return Rating(tier, frozenset(scopes), domain)
        for suffix, (tier, scopes) in SUFFIXES.items():
            if host.endswith(suffix):
                return Rating(tier, frozenset(scopes), host)
        if manufacturer(host, product):
            return Rating('primary', frozenset({'nutrition'}), host)
    if (source_id or '').startswith('kb:'):
        return Rating(KNOWLEDGE_BASE[0], frozenset(KNOWLEDGE_BASE[1]), 'HercFit knowledge base')
    return Rating('unknown', frozenset(), host or None)


def social(url):
    host = (urlparse(url or '').hostname or '').lower().removeprefix('www.')
    return any(host == domain or host.endswith('.' + domain) for domain in SOCIAL)


def allows(source_id, url, scope):
    return scope in rate(source_id, url).scopes


def quality_gate(claims, url_of, product=None):
    """At least one primary/professional source, or two distinct secondary sources."""
    tiers = {claim.source_id: rate(claim.source_id, url_of(claim.source_id), product).tier for claim in claims}
    strong = any(tier in {'primary', 'professional'} for tier in tiers.values())
    return strong or sum(1 for tier in tiers.values() if tier == 'secondary') >= 2
