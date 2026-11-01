"""Sổ đăng ký nguồn do code quản lý: độ tin cậy của một nguồn đến từ nhà xuất bản, không bao giờ từ nhãn của model.

Các hạng: primary (cơ quan y tế công cộng, cơ sở dữ liệu dinh dưỡng quốc gia, Compendium of
Physical Activities), professional (hiệp hội chuyên môn, bệnh viện, đại học và
cơ sở tri thức do người vận hành tuyển chọn), secondary (truyền thông sức khoẻ và tài liệu tham khảo uy tín).
Mọi thứ khác là 'unknown': dùng được làm văn bản bổ trợ, không bao giờ được cổng chất lượng tính.

Phạm vi giới hạn những trường mà một nguồn được phép hỗ trợ. Giá trị MET ảnh hưởng ước tính calo,
nên chỉ nguồn có phạm vi 'met' mới hỗ trợ được configuration.default_met.
"""
from dataclasses import dataclass
from urllib.parse import urlparse

from domains.catalog.models.foods import normalize_food_text

TIER_RANK = {'primary': 0, 'professional': 1, 'secondary': 2, 'unknown': 3}
ALL = frozenset({'nutrition', 'exercise', 'qa'})

# So khớp theo hostname hoặc bất kỳ miền cha nào ("fdc.nal.usda.gov" khớp với "usda.gov").
REGISTRY = {
    # Mức tiêu hao năng lượng của hoạt động thể chất
    'pacompendium.com': ('primary', ALL | {'met'}),
    'compendiumofphysicalactivities.org': ('primary', ALL | {'met'}),
    'acsm.org': ('professional', ALL | {'met'}),
    # Cơ quan y tế công cộng và cơ sở dữ liệu quốc gia
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
    # Hiệp hội chuyên môn, bệnh viện và trường đại học
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
    # Tài liệu tham khảo và truyền thông sức khoẻ uy tín
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
    # Các báo lớn của Việt Nam (chuyên mục sức khoẻ trích dẫn bác sĩ và viện dinh dưỡng)
    'tuoitre.vn': ('secondary', ALL),
    'thanhnien.vn': ('secondary', ALL),
    'vnexpress.net': ('secondary', ALL),
    'dantri.com.vn': ('secondary', ALL),
    'vietnamnet.vn': ('secondary', ALL),
    'nld.com.vn': ('secondary', ALL),
    'laodong.vn': ('secondary', ALL),
}
# Nền tảng mạng xã hội: bài đăng là ý kiến và trang thường chặn trích xuất; không bao giờ được xếp hạng,
# chỉ hiển thị cho người dùng như ước tính chưa kiểm chứng.
SOCIAL = frozenset({'tiktok.com', 'facebook.com', 'threads.com', 'threads.net', 'instagram.com', 'youtube.com',
                    'x.com', 'twitter.com', 'reddit.com'})
# Các host chính phủ và học thuật không được liệt kê riêng.
SUFFIXES = {'.gov': ('professional', ALL), '.gov.vn': ('professional', ALL), '.edu': ('professional', ALL),
            '.edu.vn': ('professional', ALL)}
KNOWLEDGE_BASE = ('professional', ALL)
# Nền tảng chứa nhiều thương hiệu không bao giờ là "nhà sản xuất".
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
    """Đánh giá một nguồn bằng chứng. Đoạn trích cơ sở tri thức (id 'kb:') do người vận hành tuyển chọn;
    URL gốc của chúng, khi biết, vẫn có thể cấp một phạm vi hẹp hơn trong sổ đăng ký như MET.
    `product` (tên một thực phẩm đã tra cứu) cho phép trang của chính thương hiệu được đánh giá như nhãn sản phẩm."""
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
    """Ít nhất một nguồn primary/professional, hoặc hai nguồn secondary khác nhau."""
    tiers = {claim.source_id: rate(claim.source_id, url_of(claim.source_id), product).tier for claim in claims}
    strong = any(tier in {'primary', 'professional'} for tier in tiers.values())
    return strong or sum(1 for tier in tiers.values() if tier == 'secondary') >= 2
