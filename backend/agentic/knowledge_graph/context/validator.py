"""Validator và bộ viết lại cho Cypher sinh ra: phần p (chính sách) của G_C = f(G_K, q, u, t, i, s, p).

Fail-closed: chỉ nhận một tập con Cypher chỉ đọc mà validator hiểu trọn vẹn, mọi thứ khác bị từ chối kèm mã lỗi.
Neo4j Community không có phân quyền theo người dùng, nên cách ly dữ liệu do đây bảo đảm, không phải do model:

- Mỗi mẫu nút phải có đúng một nhãn trong schema.LABELS; quan hệ phải có kiểu trong schema và nối đúng hai nhãn.
- Nút riêng (private) được VIẾT LẠI thành {owner_id: $owner, deleted: false}; model ghi owner khác thì bị từ chối.
- Nút mixed (Food, Exercise) chỉ đọc được khi đi qua quan hệ từ một nút đã thuộc người dùng, hoặc mang owner_id/scope
  tường minh; nếu không, nó bị giới hạn về {scope: 'SYSTEM'}.
- Run/Execution bị giới hạn trong các phiên còn sống ($session_ids, $generations) như thẻ tri thức tĩnh.
- Biểu thức không được chứa mẫu đồ thị (mũi tên), map literal hay subquery ({…}), nên không có đường nào khác tới dữ
  liệu ngoài các mẫu nút đã kiểm tra. Hàm chỉ trong danh sách cho phép; tham số chỉ trong PARAMS.
- Không ngày hay ID viết cứng: thời gian luôn là $start/$end do code chuẩn hoá.
"""

import re
from dataclasses import dataclass, field

from ..schema import ENDPOINTS, LABELS, REL_PROPS, REL_TYPES, SESSION_SCOPED

MAX_LIMIT = 50
MAX_HOPS = 2
MAX_LENGTH = 2500
MAX_MATCHES = 6
PARAMS = frozenset(
    {
        "owner",
        "start",
        "end",
        "today",
        "now",
        "terms",
        "grain",
        "session_id",
        "session_ids",
        "generations",
    }
)
CLAUSE_STARTS = frozenset({"MATCH", "OPTIONAL", "WITH", "UNWIND", "RETURN"})
# Từ khoá được phép bên trong biểu thức.
EXPRESSION_WORDS = frozenset(
    {
        "AND",
        "OR",
        "NOT",
        "XOR",
        "IN",
        "IS",
        "NULL",
        "TRUE",
        "FALSE",
        "STARTS",
        "ENDS",
        "CONTAINS",
        "CASE",
        "WHEN",
        "THEN",
        "ELSE",
        "END",
        "DISTINCT",
    }
)
FUNCTIONS = frozenset(
    {
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "collect",
        "percentilecont",
        "percentiledisc",
        "stdev",
        "round",
        "floor",
        "ceil",
        "abs",
        "sqrt",
        "sign",
        "coalesce",
        "size",
        "head",
        "last",
        "tail",
        "reverse",
        "range",
        "tostring",
        "tointeger",
        "tofloat",
        "toboolean",
        "tolower",
        "toupper",
        "trim",
        "ltrim",
        "rtrim",
        "substring",
        "left",
        "right",
        "split",
        "replace",
        "labels",
        "type",
        "any",
        "all",
        "none",
        "single",
        "reduce",
        "date",
        "datetime",
        "duration",
        "date.truncate",
        "datetime.truncate",
        "duration.between",
        "duration.indays",
    }
)
# Thuộc tính nội bộ của projection: không bao giờ được đọc (chúng mang khoá, ID nguồn hoặc JSON thô).
INTERNAL = frozenset(
    {
        "key",
        "owner_id",
        "fact_json",
        "search_text",
        "source_id",
        "snapshot_json",
        "model_json",
        "prev_key",
        "about_keys",
        "target_keys",
        "food_key",
        "session_generation",
        "deleted",
        "pruned",
        "lock",
        "source_version",
        "projection_version",
        "business_at",
        "source_at",
        "projected_at",
        "kind",
        "scope",
        "run_id",
    }
)
DATE_LITERAL = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}")
ID_LITERAL = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-|[0-9a-f]{24,}", re.I)
TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
   |(?P<comment>//[^\n]*|/\*.*?\*/)
   |(?P<str>'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*")
   |(?P<num>\d+\.\d+(?:[eE][-+]?\d+)?|\d+(?:[eE][-+]?\d+)?)
   |(?P<param>\$[A-Za-z_][A-Za-z0-9_]*)
   |(?P<ident>[A-Za-z_][A-Za-z0-9_]*)
   |(?P<op><>|<=|>=|=~|\.\.|[-+*/%^=<>(){}\[\],.:|;!&])
    """,
    re.X | re.S,
)


class CypherRejected(ValueError):
    """Truy vấn ngoài tập con cho phép. `code` là nhãn ổn định cho telemetry, `detail` giúp model tự sửa."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


@dataclass
class Tok:
    kind: str
    text: str
    start: int
    end: int

    @property
    def up(self):
        return self.text.upper() if self.kind == "ident" else self.text


@dataclass
class Checked:
    """Truy vấn đã viết lại (chạy được) cùng những gì nó dùng."""

    cypher: str
    labels: set = field(default_factory=set)
    relationships: set = field(default_factory=set)
    params: set = field(default_factory=set)


def tokenize(text):
    tokens, position = [], 0
    while position < len(text):
        match = TOKEN.match(text, position)
        if not match:
            raise CypherRejected("character", repr(text[position : position + 12]))
        kind = match.lastgroup
        if kind not in {"ws", "comment"}:
            tokens.append(Tok(kind, match.group(0), match.start(), match.end()))
        position = match.end()
    return tokens


@dataclass
class _Node:
    var: str | None
    label: str
    bound: bool  # biến đã khai báo ở mẫu trước: chỉ lọc thêm, không gắn lại phạm vi
    keys: dict
    open_tok: Tok
    map_close: Tok | None
    close_tok: Tok


class _Validator:
    def __init__(self, text):
        if len(text) > MAX_LENGTH:
            raise CypherRejected("too_long", f"tối đa {MAX_LENGTH} ký tự")
        self.text = text
        self.t = tokenize(text)
        self.i = 0
        self.vars = {}  # tên -> nhãn nút | ("rel", kiểu) | None (giá trị)
        self.safe = set()  # biến nút đã thuộc người dùng hoặc là dữ liệu hệ thống
        self.inserts = []  # (vị trí, văn bản) chèn vào bản gốc
        self.used = Checked(text)
        self.generated = 0
        self.matches = 0

    # ------------------------------------------------------------ tiện ích con trỏ

    def peek(self, offset=0):
        index = self.i + offset
        return self.t[index] if index < len(self.t) else None

    def take(self):
        tok = self.peek()
        if tok is None:
            raise CypherRejected("unexpected_end")
        self.i += 1
        return tok

    def expect(self, text):
        tok = self.take()
        if tok.up != text:
            raise CypherRejected("syntax", f"cần '{text}' nhưng gặp '{tok.text}'")
        return tok

    def at(self, *texts):
        tok = self.peek()
        return tok is not None and tok.up in texts

    # ------------------------------------------------------------ truy vấn

    def run(self):
        if not self.t:
            raise CypherRejected("empty")
        returned = False
        while self.peek() is not None:
            if returned:
                raise CypherRejected("return_last", "RETURN phải là mệnh đề cuối")
            tok = self.peek()
            word = tok.up if tok.kind == "ident" else None
            if word == "MATCH":
                self.take()
                self.match()
            elif word == "OPTIONAL":
                self.take()
                self.expect("MATCH")
                self.match()
            elif word == "WITH":
                self.take()
                self.projection(final=False)
            elif word == "UNWIND":
                self.take()
                self.expression(stops={"AS"})
                self.expect("AS")
                self.bind_value(self.take())
            elif word == "RETURN":
                self.take()
                self.projection(final=True)
                returned = True
            else:
                raise CypherRejected("clause", f"không cho phép '{tok.text}'")
        if not returned:
            raise CypherRejected("no_return", "truy vấn phải kết thúc bằng RETURN")
        if self.matches == 0:
            raise CypherRejected("no_match")
        return self.render()

    def render(self):
        text = self.text
        for position, insert in sorted(self.inserts, key=lambda item: item[0], reverse=True):
            text = text[:position] + insert + text[position:]
        self.used.cypher = text.strip()
        return self.used

    # ------------------------------------------------------------ MATCH

    def match(self):
        self.matches += 1
        if self.matches > MAX_MATCHES:
            raise CypherRejected("too_many_matches", f"tối đa {MAX_MATCHES} MATCH")
        predicates = []
        while True:
            self.path(predicates)
            if self.at(","):
                self.take()
                continue
            break
        last = self.t[self.i - 1]
        if self.at("WHERE"):
            where = self.take()
            self.expression(stops=CLAUSE_STARTS)
            end = self.t[self.i - 1].end
            if predicates:
                self.inserts.append((where.end, " ("))
                self.inserts.append((end, ") AND " + " AND ".join(predicates)))
        elif predicates:
            self.inserts.append((last.end, " WHERE " + " AND ".join(predicates)))

    def path(self, predicates):
        tok, nxt = self.peek(), self.peek(1)
        if tok is not None and tok.kind == "ident" and nxt is not None and nxt.text == "=":
            raise CypherRejected("path_variable", "không gán biến cho đường đi")
        nodes, rels = [self.node()], []
        while self.at("-", "<"):
            rels.append(self.relationship())
            nodes.append(self.node())
        for index, rel in enumerate(rels):
            self.check_endpoints(nodes[index], rel, nodes[index + 1])
        for index, node in enumerate(nodes):
            neighbours = nodes[max(0, index - 1) : index] + nodes[index + 1 : index + 2]
            self.scope(node, neighbours, predicates)

    def node(self):
        open_tok = self.expect("(")
        var = label = None
        keys, map_close = {}, None
        if self.peek() is not None and self.peek().kind == "ident":
            var = self.take().text
        if self.at(":"):
            self.take()
            name = self.take()
            if name.kind != "ident" or name.text not in LABELS:
                raise CypherRejected("label", f"nhãn '{name.text}' không có trong lược đồ")
            label = name.text
            if self.at(":", "|", "&", "!", "%"):
                raise CypherRejected("label_expression", "mỗi nút đúng một nhãn")
        if self.at("{"):
            keys, map_close = self.property_map()
        close_tok = self.expect(")")
        bound = var is not None and var in self.vars
        if bound:
            known = self.vars[var]
            if not isinstance(known, str):
                raise CypherRejected("variable", f"'{var}' không phải một nút")
            if label and label != known:
                raise CypherRejected("label", f"'{var}' đã là {known}")
            label = known
        elif label is None:
            raise CypherRejected("label_required", "mỗi nút mới phải có nhãn")
        if var is not None and not bound:
            if var.upper() in CLAUSE_STARTS | EXPRESSION_WORDS or var.startswith("_cg"):
                raise CypherRejected("variable", f"tên biến '{var}' không hợp lệ")
            self.vars[var] = label
        for key in keys:
            self.check_key(LABELS[label], label, key, keys[key])
        self.used.labels.add(label)
        return _Node(var, label, bound, keys, open_tok, map_close, close_tok)

    def property_map(self):
        self.expect("{")
        keys = {}
        while True:
            name = self.take()
            if name.kind != "ident":
                raise CypherRejected("syntax", "khoá thuộc tính không hợp lệ")
            self.expect(":")
            value = self.take()
            if (
                value.kind == "op"
                and value.text == "-"
                and self.peek()
                and self.peek().kind == "num"
            ):
                value = self.take()
            if value.kind == "param":
                self.check_param(value)
            elif value.kind == "str":
                self.check_string(value)
            elif not (value.kind == "num" or value.up in {"TRUE", "FALSE", "NULL"}):
                raise CypherRejected("map_value", "giá trị trong mẫu nút chỉ là tham số hoặc hằng")
            keys[name.text] = value
            if self.at(","):
                self.take()
                continue
            close = self.expect("}")
            return keys, close

    def check_key(self, spec, label, key, value):
        if key == "owner_id":
            if spec.scope == "shared" or value.text != "$owner":
                raise CypherRejected(
                    "owner", "owner_id chỉ có thể là $owner (và thường không cần viết)"
                )
            return
        if key == "scope":
            if spec.scope != "mixed" or value.text not in {"'SYSTEM'", '"SYSTEM"'}:
                raise CypherRejected(
                    "scope", "scope chỉ dùng cho Food/Exercise với giá trị 'SYSTEM'"
                )
            return
        if key not in spec.props:
            raise CypherRejected("property", f"{label} không có thuộc tính '{key}'")

    def relationship(self):
        incoming = False
        if self.at("<"):
            self.take()
            incoming = True
        self.expect("-")
        types, hops = [], None
        if self.at("["):
            self.take()
            if self.peek() is not None and self.peek().kind == "ident":
                var = self.take().text
                if var in self.vars:
                    raise CypherRejected("variable", f"'{var}' đã được dùng")
                self.vars[var] = ("rel", types)
            if self.at(":"):
                self.take()
                while True:
                    name = self.take()
                    if name.kind != "ident" or name.text not in REL_TYPES:
                        raise CypherRejected(
                            "relationship", f"quan hệ '{name.text}' không có trong lược đồ"
                        )
                    types.append(name.text)
                    if self.at("|"):
                        self.take()
                        if self.at(":"):
                            self.take()
                        continue
                    break
            if self.at("*"):
                self.take()
                low = high = None
                if self.peek() is not None and self.peek().kind == "num":
                    low = int(self.take().text)
                if self.at(".."):
                    self.take()
                    if self.peek() is not None and self.peek().kind == "num":
                        high = int(self.take().text)
                else:
                    high = low
                if high is None or high > MAX_HOPS or (low is not None and low > high):
                    raise CypherRejected("hops", f"độ dài thay đổi phải có cận trên ≤ {MAX_HOPS}")
                hops = high
            if self.at("{"):
                keys, _ = self.property_map()
                for key in keys:
                    if not any(key in REL_PROPS.get(kind, {}) for kind in types):
                        raise CypherRejected("property", f"quan hệ không có thuộc tính '{key}'")
            self.expect("]")
        self.expect("-")
        outgoing = False
        if self.at(">"):
            self.take()
            outgoing = True
        if incoming and outgoing:
            raise CypherRejected("syntax", "quan hệ chỉ một hướng")
        if not types:
            raise CypherRejected("relationship_type", "quan hệ phải có kiểu, vd. -[:HAS_ITEM]->")
        self.used.relationships.update(types)
        return types, ("in" if incoming else "out" if outgoing else "both"), hops

    def check_endpoints(self, left, rel, right):
        types, direction, hops = rel
        for kind in types:
            forward = (left.label, kind, right.label) in ENDPOINTS
            backward = (right.label, kind, left.label) in ENDPOINTS
            ok = (
                forward
                if direction == "out"
                else backward
                if direction == "in"
                else forward or backward
            )
            if hops is not None and not any(a == b for a, k, b in ENDPOINTS if k == kind):
                raise CypherRejected("hops", f"{kind} không dùng được với độ dài thay đổi")
            if not ok:
                raise CypherRejected(
                    "endpoints",
                    f"({left.label})-[:{kind}]-({right.label}) sai hướng hoặc không có trong lược đồ",
                )

    def scope(self, node, neighbours, predicates):
        """Gắn phạm vi người dùng vào lần khai báo đầu tiên của nút; nút đã khai báo giữ phạm vi cũ."""
        spec = LABELS[node.label]
        if node.bound:
            return
        adds = []
        if spec.scope == "private":
            adds = ["owner_id: $owner", "deleted: false"]
            safe = True
        elif spec.scope == "mixed":
            explicit = "owner_id" in node.keys or "scope" in node.keys
            anchored = any(
                LABELS[n.label].scope == "private" or (n.var in self.safe and n.bound)
                for n in neighbours
            )
            if explicit:
                adds = ["deleted: false"]
            elif not anchored:
                adds = ["scope: 'SYSTEM'", "deleted: false"]
            safe = True
        else:
            safe = True
        if safe and node.var:
            self.safe.add(node.var)
        var = node.var
        if node.label in SESSION_SCOPED:
            if var is None:
                self.generated += 1
                var = f"_cg{self.generated}"
                self.inserts.append((node.open_tok.end, var))
                self.vars[var] = node.label
            predicates.append(
                f"{var}.session_id IN $session_ids AND {var}.session_generation = $generations[{var}.session_id]"
            )
            self.used.params.update({"session_ids", "generations"})
        if not adds:
            return
        if "owner_id: $owner" in adds:
            self.used.params.add("owner")
        if node.map_close is not None:
            present = {"owner_id"} & set(node.keys)
            text = ", ".join(a for a in adds if a.split(":")[0] not in present)
            if text:
                self.inserts.append((node.map_close.start, ", " + text))
        else:
            self.inserts.append((node.close_tok.start, " {" + ", ".join(adds) + "}"))

    # ------------------------------------------------------------ WITH / RETURN

    def projection(self, final):
        if self.at("DISTINCT"):
            self.take()
        if self.at("*"):
            raise CypherRejected("star", "liệt kê cột cụ thể thay vì *")
        # Sau WITH chỉ còn các tên được chiếu (ngữ nghĩa Cypher). Phải đặt lại phạm vi: nếu không, `WITH count(m) AS c
        # MATCH (m:Meal)` sẽ khai báo một nút Meal MỚI mà validator tưởng là nút cũ đã gắn owner.
        projected, projected_safe = {}, set()
        while True:
            start = self.i
            self.expression(
                stops={"AS", "ORDER", "SKIP", "LIMIT", "WHERE"} | CLAUSE_STARTS, comma=True
            )
            single = (
                self.t[start] if self.i == start + 1 and self.t[start].kind == "ident" else None
            )
            source = single.text if single is not None and single.text in self.vars else None
            name = source
            if self.at("AS"):
                self.take()
                alias = self.take()
                self.check_name(alias)
                name = alias.text
            if name is not None:
                # Một biến nút được chiếu (kể cả đổi tên) vẫn là đúng nút đã giới hạn phạm vi.
                projected[name] = self.vars.get(source) if source else None
                if source in self.safe:
                    projected_safe.add(name)
            if self.at(","):
                self.take()
                continue
            break
        # ORDER BY thấy cả tên cũ lẫn tên vừa chiếu (alias).
        for name, label in projected.items():
            self.vars.setdefault(name, label)
            if name in projected_safe:
                self.safe.add(name)
        if self.at("ORDER"):
            self.take()
            self.expect("BY")
            while True:
                self.expression(
                    stops={"SKIP", "LIMIT", "WHERE", "ASC", "DESC", "ASCENDING", "DESCENDING"}
                    | CLAUSE_STARTS,
                    comma=True,
                )
                if self.at("ASC", "DESC", "ASCENDING", "DESCENDING"):
                    self.take()
                if self.at(","):
                    self.take()
                    continue
                break
        if self.at("SKIP"):
            self.take()
            self.expression(stops={"LIMIT", "WHERE"} | CLAUSE_STARTS)
        limited = False
        if self.at("LIMIT"):
            self.take()
            tok = self.take()
            if tok.kind != "num" or int(float(tok.text)) > MAX_LIMIT:
                raise CypherRejected("limit", f"LIMIT là số nguyên ≤ {MAX_LIMIT}")
            limited = True
        if not final:
            self.vars, self.safe = projected, projected_safe
            if self.at("WHERE"):
                self.take()
                self.expression(stops=CLAUSE_STARTS)
        if final and not limited:
            self.inserts.append((self.t[self.i - 1].end, f" LIMIT {MAX_LIMIT}"))

    @staticmethod
    def check_name(tok):
        if (
            tok.kind != "ident"
            or tok.up in CLAUSE_STARTS | EXPRESSION_WORDS
            or tok.text.startswith("_cg")
        ):
            raise CypherRejected("alias", f"tên '{tok.text}' không hợp lệ")

    def bind_value(self, tok):
        self.check_name(tok)
        if tok.text in self.vars:
            raise CypherRejected("variable", f"'{tok.text}' đã được dùng")
        self.vars[tok.text] = None

    # ------------------------------------------------------------ biểu thức

    def check_param(self, tok):
        name = tok.text[1:]
        if name not in PARAMS:
            raise CypherRejected(
                "parameter", f"tham số ${name} không tồn tại; có: " + ", ".join(sorted(PARAMS))
            )
        self.used.params.add(name)

    @staticmethod
    def check_string(tok):
        if DATE_LITERAL.search(tok.text) or ID_LITERAL.search(tok.text):
            raise CypherRejected("literal", "không viết cứng ngày hay ID; dùng $start/$end/$today")

    def expression(self, stops, comma=False):
        depth, started = 0, self.i
        while self.peek() is not None:
            tok = self.peek()
            prev = self.t[self.i - 1] if self.i > started else None
            if depth == 0:
                if comma and tok.text == ",":
                    break
                if tok.kind == "ident" and tok.up in stops:
                    # "STARTS WITH"/"ENDS WITH" là toán tử, không phải mệnh đề WITH.
                    if not (
                        tok.up == "WITH" and prev is not None and prev.up in {"STARTS", "ENDS"}
                    ):
                        break
                if tok.text in {")", "]"}:
                    break
            self.take()
            nxt = self.peek()
            if tok.kind == "str":
                self.check_string(tok)
            elif tok.kind == "param":
                self.check_param(tok)
            elif tok.kind == "op":
                if tok.text in {"{", "}", ";", "=~", "!", "&"}:
                    raise CypherRejected(
                        "expression", f"không cho phép '{tok.text}' trong biểu thức"
                    )
                if tok.text == "-" and nxt is not None and nxt.text in {"[", "-", ">"}:
                    raise CypherRejected(
                        "pattern_in_expression", "không dùng mẫu đồ thị trong WHERE/RETURN"
                    )
                if tok.text == "<" and nxt is not None and nxt.text == "-":
                    raise CypherRejected(
                        "pattern_in_expression", "không dùng mẫu đồ thị trong WHERE/RETURN"
                    )
                if tok.text in {"(", "["}:
                    depth += 1
                elif tok.text in {")", "]"}:
                    depth -= 1
            elif tok.kind == "ident":
                self.identifier(tok, prev, nxt, depth)
        if depth != 0:
            raise CypherRejected("syntax", "ngoặc không cân")
        if self.i == started:
            raise CypherRejected("syntax", "thiếu biểu thức")

    def identifier(self, tok, prev, nxt, depth):
        word = tok.up
        if prev is not None and prev.text == "." and not (nxt is not None and nxt.text == "("):
            owner = self.t[self.i - 3] if self.i >= 3 else None
            self.check_property(owner, tok)  # trước từ khoá: `p.end` là thuộc tính, không phải END
            return
        if word in EXPRESSION_WORDS:
            return  # kể cả "OR (" / "NOT (" / "IN [": toán tử, không phải hàm
        if nxt is not None and nxt.text == "(":
            name = tok.text.lower()
            if prev is not None and prev.text == ".":
                return  # đã xử lý cùng phần đầu của hàm có không gian tên
            if name not in FUNCTIONS:
                raise CypherRejected("function", f"hàm '{tok.text}' không được phép")
            return
        if (
            nxt is not None
            and nxt.text == "."
            and self.peek(1) is not None
            and self.peek(2) is not None
            and self.peek(2).text == "("
        ):
            name = (tok.text + "." + self.peek(1).text).lower()
            if name not in FUNCTIONS:
                raise CypherRejected("function", f"hàm '{name}' không được phép")
            return
        if prev is not None and prev.text == ":":
            if tok.text not in LABELS:
                raise CypherRejected("label", f"nhãn '{tok.text}' không có trong lược đồ")
            return
        if word == "WHERE" and depth > 0:
            return  # [x IN list WHERE ...], any(x IN list WHERE ...)
        if (
            depth > 0
            and nxt is not None
            and (nxt.up == "IN" or nxt.text == "=")
            and tok.text not in self.vars
        ):
            self.vars[tok.text] = None  # biến của list comprehension / reduce
            return
        if tok.text in self.vars:
            return
        raise CypherRejected(
            "identifier", f"'{tok.text}' chưa được khai báo hoặc là từ khoá không được phép"
        )

    def check_property(self, owner, tok):
        if tok.text in INTERNAL:
            raise CypherRejected("property", f"'{tok.text}' là thuộc tính nội bộ")
        if owner is None or owner.kind != "ident":
            return
        known = self.vars.get(owner.text)
        if isinstance(known, str):
            if tok.text not in LABELS[known].props:
                raise CypherRejected("property", f"{known} không có thuộc tính '{tok.text}'")
        elif isinstance(known, tuple):
            if not any(tok.text in REL_PROPS.get(kind, {}) for kind in known[1]):
                raise CypherRejected("property", f"quan hệ không có thuộc tính '{tok.text}'")


def validate(cypher):
    """Truy vấn đã viết lại, chạy được với tham số do code gán; ném CypherRejected nếu ngoài tập con cho phép."""
    return _Validator(cypher).run()
