"""データとAPIの型。画面担当とサーバーの取り決めはこのファイルと tests/fixtures/api_examples.json。"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------- データ（data/*.json） ----------

Category = Literal["cleanser", "lotion", "serum", "emulsion", "cream", "sunscreen", "other"]
Timing = Literal["morning", "night"]


class Source(BaseModel):
    source_id: str
    url: str
    title: str
    publisher: str | None = None
    checked_at: str


class Claim(BaseModel):
    claim_id: str
    text: str  # 公式表示の原文。言い換えない
    type: Literal["efficacy_tested", "quasi_drug_efficacy", "marketing"]
    concern_tags: list[str] = []
    source_id: str


class Usage(BaseModel):
    timing: list[Timing] = []
    timing_strength: Literal["required", "recommended", "not_stated", "unknown"] = "unknown"
    order_note: str | None = None
    amount_note: str | None = None
    source_id: str | None = None


class Volume(BaseModel):
    value: float
    unit: str


class Unknown(BaseModel):
    field: str
    reason: str


class ProductMedia(BaseModel):
    """商品写真。registered は人が公式ページで確かめた画像、yahoo / rakuten は各社の公式APIで照合した画像。"""

    src: str
    source_url: str
    credit: str
    provider: Literal["registered", "yahoo", "rakuten"] = "registered"
    checked_at: str | None = None

    @field_validator("src")
    @classmethod
    def safe_src(cls, value: str) -> str:
        # 画面に出すURLなので、https の画像だけを通す（rerankでクライアントから届く値も含む）
        if value.startswith("https://") and len(value) <= 2048:
            return value
        raise ValueError("画像のURLは https のURLにしてください")

    @field_validator("source_url")
    @classmethod
    def safe_source_url(cls, value: str) -> str:
        if value.startswith(("https://", "http://")) and len(value) <= 2048:
            return value
        raise ValueError("商品ページのURLは http(s) にしてください")


class Product(BaseModel):
    product_id: str
    is_dummy: bool = False
    role: Literal["candidate", "owned"]
    demo_role: str | None = None
    brand: str
    maker: str | None = None
    name: str
    variant: str | None = None
    region: str = "JP"
    category: Category
    regulatory_class: Literal["cosmetic", "quasi_drug"] = "cosmetic"
    active_ingredients: list[str] = []
    volume: Volume | None = None
    price_jpy_tax_included: int | None = Field(default=None, gt=0)
    price_note: str | None = None
    price_source_id: str | None = None
    ingredients_full: list[str] | None = None
    ingredients_source_id: str | None = None
    ingredients_complete: bool = True  # 全成分表示の全体を確認できたか（検索で一部しか取れないことがある）
    searched_as: str | None = None  # 本人が確定した品名（検索に使った名前）
    claims: list[Claim] = []
    maker_texture_description: str | None = None
    texture_expectation: Literal["heavy", "light", "medium"] | None = None
    usage: Usage = Usage()
    cautions: list[str] = []
    sources: list[Source] = []
    checked_at: str
    data_version: str
    unknown: list[Unknown] = []
    name_aliases: list[str] = []  # 登録商品の別の書き方。写真や手入力の品名との照合に使う
    media: ProductMedia | None = None


class Review(BaseModel):
    review_id: str
    product_id: str
    is_dummy: bool = False
    medium: Literal["cosme", "lips", "amazon", "official", "other"]
    url: str
    posted_at: str | None = None
    product_version_note: str | None = None
    skin_type: str | None = None
    usage_period: str | None = None
    incentivized: bool | None = None  # 媒体が表示する提供・PR表示。真偽の保証ではない
    summary: str = Field(max_length=200)
    collected_at: str
    duplicate_of: str | None = None
    source_title: str | None = None  # その場の検索で得た出典の名前（ドメイン）


class Direction(BaseModel):
    direction_id: str
    label: str
    concern: str
    summary: str
    member_ingredients: list[str] = []


class Evidence(BaseModel):
    evidence_id: str
    direction_id: str
    ingredient_names: list[str]
    concern: str
    summary: str
    scope: str
    limitations: str
    cautions: str | None = None
    source: Source


class AliasEntry(BaseModel):
    canonical: str
    aliases: list[str] = []
    inci: str | None = None
    direction_ids: list[str] = []


# ---------- 利用者の条件 ----------

Aspect = Literal["stickiness", "absorption", "spread", "scent", "moisture", "makeup", "irritation"]
ASPECT_LABELS: dict[str, str] = {
    "stickiness": "ベタつき",
    "absorption": "なじみ",
    "spread": "伸び",
    "scent": "香り",
    "moisture": "保湿感",
    "makeup": "メイク前の使いやすさ",
    "irritation": "刺激感",
}
PriorityKey = Literal["concern", "stickiness", "price"]
PRIORITY_LABELS: dict[str, str] = {"concern": "悩みとの関連", "stickiness": "ベタつきの少なさ", "price": "価格"}
DEFAULT_PRIORITIES: list[str] = ["concern", "stickiness", "price"]
LIGHT_PRIORITIES: list[str] = ["stickiness", "concern", "price"]


class TexturePreference(BaseModel):
    aspect: Aspect
    preference: Literal["avoid", "prefer"]
    note: str | None = None


FINE_LINES_WORDS = ("小じわ", "小ジワ", "しわ", "シワ", "皺")


def concern_id_for(label: str | None) -> str:
    """悩みの言葉から、内部の区分を決める。小じわは登録済みの資料、それ以外（custom）はその場で調べる。"""
    text = (label or "").strip()
    if not text:
        return ""
    return "fine_lines" if any(w in text for w in FINE_LINES_WORDS) else "custom"


class Conditions(BaseModel):
    concern: str = "fine_lines"  # fine_lines（登録済みの資料あり）/ custom（その場で調べる）/ 空（未入力）
    concern_label: str = "小じわ"  # 本人の言葉のまま
    concern_note: str | None = None  # 乾燥も気になる等の補足
    category: Category = "serum"
    budget_jpy_max: int | None = Field(default=None, ge=1)  # gt=0 はGeminiのスキーマ変換が受け付けない（exclusiveMinimum）
    texture_preferences: list[TexturePreference] = []
    keep_note: str | None = None  # 「この化粧水は残したい」の原文
    avoid_ingredients: list[str] = []
    require_texture_evidence: bool = False  # 使用感の根拠の確認を必須にするか


class IntakeRequest(BaseModel):
    text: str = Field(max_length=1000)


class IntakeResponse(BaseModel):
    conditions: Conditions
    follow_up_questions: list[str] = []


# ---------- 手持ちの確認 ----------


class ProductSummary(BaseModel):
    media: ProductMedia | None = None
    product_id: str
    brand: str
    name: str
    category: Category
    role: str
    is_dummy: bool = False


class CatalogResponse(BaseModel):
    owned_candidates: list[ProductSummary]
    data_version: str


class DetectionMatch(BaseModel):
    product_id: str
    brand: str
    name: str
    score: float


class Detection(BaseModel):
    brand: str | None = None
    name_guess: str | None = None
    alternatives: list[str] = []  # 同じ容器について考えられる、ほかの製品名
    is_sample: bool = False  # 試供品・サンプルの小袋やミニサイズ
    category: str | None = None
    visible_text: str | None = None
    matches: list[DetectionMatch] = []


class InventoryResponse(BaseModel):
    detections: list[Detection]
    note: str | None = None


# ---------- 推薦 ----------

Status = Literal["RECOMMENDATION_READY", "NEEDS_MORE_INFO", "NO_MATCH_IN_SCOPE", "HALTED"]


class OwnedItem(BaseModel):
    """写真から本人が確定した手持ち。その場の検索で全成分を調べる。"""

    brand: str | None = None
    name: str = Field(min_length=1, max_length=120)
    category: Category = "other"
    keep: bool = False

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("商品名を入力してください")
        return value.strip()


class RecommendRequest(BaseModel):
    conditions: Conditions
    owned_items: list[OwnedItem] = Field(default_factory=list, max_length=8)
    owned_product_ids: list[str] = Field(default_factory=list, max_length=8)
    keep_product_ids: list[str] = Field(default_factory=list, max_length=8)
    priorities: list[PriorityKey] = Field(default_factory=lambda: list(DEFAULT_PRIORITIES), min_length=1, max_length=3)

    @field_validator("priorities", "owned_product_ids", "keep_product_ids")
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def limit_total_owned(self):
        if len(self.owned_items) + len(self.owned_product_ids) > 8:
            raise ValueError("手持ちは合計8点までです")
        return self


class SourceRef(BaseModel):
    source_id: str
    url: str
    title: str


class ClaimView(BaseModel):
    claim_id: str
    text: str
    type: str
    source: SourceRef | None = None


class EvidenceView(BaseModel):
    evidence_id: str
    direction_id: str
    summary: str
    scope: str
    limitations: str
    source: SourceRef


class IngredientHit(BaseModel):
    name: str  # 製品の全成分表示のまま
    canonical: str
    direction_id: str


class ConcernRelevance(BaseModel):
    level: Literal["claim", "ingredient", "none"]
    label: str
    claims: list[ClaimView] = []
    ingredients: list[IngredientHit] = []
    evidence: list[EvidenceView] = []


class ReviewExample(BaseModel):
    review_id: str
    summary: str
    polarity: Literal["positive", "negative", "mixed", "unknown"]
    url: str
    medium: str
    source_title: str | None = None


class AspectSummary(BaseModel):
    aspect: Aspect
    label: str
    positive: int
    negative: int
    mixed: int
    unknown: int
    total: int  # 分析した一意の投稿数（論点に触れていない投稿は unknown）
    examples: list[ReviewExample] = []


class ReviewScope(BaseModel):
    analyzed_count: int
    media: list[str]
    period_from: str | None = None
    period_to: str | None = None
    insufficient: bool
    single_medium: bool
    incentivized_count: int = 0
    duplicates_removed: int = 0
    skin_type_stated_count: int = 0
    unit: Literal["posts", "sources"] = "posts"  # posts: 口コミ投稿 / sources: 検索で確認できた情報源
    notes: list[str] = []


class Texture(BaseModel):
    maker_description: str | None = None
    stickiness_level: Literal["good", "mixed", "bad", "insufficient"]
    stickiness_label: str
    aspects: list[AspectSummary] = []


class OwnedOverlap(BaseModel):
    canonical: str
    owned_product_ids: list[str]


class OwnedRelation(BaseModel):
    overlaps: list[OwnedOverlap] = []
    new_directions: list[str] = []
    shared_directions: list[str] = []
    unconfirmed_directions: list[str] = []
    note: str


class UsageView(BaseModel):
    timing: list[Timing] = []
    timing_strength: str
    order_note: str | None = None
    source: SourceRef | None = None


class Reason(BaseModel):
    category: Literal["concern", "texture", "owned", "price", "usage"]
    text: str
    source_ids: list[str] = []


class Explanation(BaseModel):
    summary: str
    reasons: list[Reason] = []
    tradeoffs: list[str] = []
    unverified: list[str] = []


class CandidateView(BaseModel):
    media: ProductMedia | None = None
    product_id: str
    brand: str
    name: str
    category: Category
    is_dummy: bool = False
    regulatory_class: str
    price_jpy: int | None
    price_note: str | None = None
    volume_text: str | None = None
    price_checked_at: str | None = None
    price_source: SourceRef | None = None
    concern_relevance: ConcernRelevance
    texture: Texture
    review_scope: ReviewScope
    owned_relation: OwnedRelation
    usage: UsageView
    cautions: list[str] = []
    unknown: list[str] = []
    explanation: Explanation | None = None
    rank: int
    rank_reason: str  # 1つ上・下との比較で、最初に差がついた観点


class RoutineStep(BaseModel):
    media: ProductMedia | None = None
    product_id: str
    brand: str
    name: str
    category: Category
    is_new: bool = False


class RoutineSlotPlan(BaseModel):
    morning: list[RoutineStep]
    night: list[RoutineStep]


class RoutineDiff(BaseModel):
    type: Literal["add", "keep", "move", "remove"]
    product_id: str
    slot: Literal["morning", "night", "both", "unplaced"]
    reason: str


class RoutinePlan(BaseModel):
    product_id: str | None  # 候補ID。None は今の棚
    plan: RoutineSlotPlan
    diff: list[RoutineDiff] = []
    steps_morning: int
    steps_night: int
    status: Literal["ok", "conflict", "unknown_usage"]
    notes: list[str] = []
    unplaced: list[RoutineStep] = []  # 用法を確認できるまで朝夜に配置しない


class Comparison(BaseModel):
    winner: str
    loser: str
    deciding_aspect: str
    detail: str


class Ranking(BaseModel):
    priorities: list[PriorityKey]
    order: list[str]
    why_top: str
    comparisons: list[Comparison] = []
    excluded: list[dict] = []  # 必須条件で外れた候補と理由


class DirectionView(BaseModel):
    direction_id: str
    label: str
    why: str


class OwnedProductView(BaseModel):
    media: ProductMedia | None = None
    product_id: str
    brand: str
    name: str
    category: Category
    is_dummy: bool = False
    searched_as: str | None = None
    ingredients_available: bool
    ingredients_complete: bool = True
    ingredients_full: list[str] = []
    ingredient_source: SourceRef | None = None
    directions_found: list[IngredientHit] = []
    claims: list[ClaimView] = []


class DirectionCoverage(BaseModel):
    direction_id: str
    label: str
    status: Literal["found", "not_found", "unknown"]
    product_ids: list[str] = []
    ingredients: list[str] = []
    note: str


class OwnedAnalysis(BaseModel):
    products: list[OwnedProductView]
    common_ingredients: list[OwnedOverlap] = []
    coverage: list[DirectionCoverage] = []


class ResearchStep(BaseModel):
    """調査の記録。何を検索し、何が見つかり、どう判断したか。"""

    step: Literal["concern", "owned", "discover", "candidate_facts", "candidate_reviews"]
    target: str
    status: Literal["ok", "partial", "failed"]
    summary: str
    details: list[str] = []
    queries: list[str] = []
    sources: list[SourceRef] = []


class Analysis(BaseModel):
    """/api/rerank へそのまま送り返す分析結果。サーバーは投稿IDを照合して検算する。"""

    plan_directions: list[str] = []  # 調査計画で選ばれた方向性（direction_id）
    bundle: dict | None = None  # その場で調べた製品・口コミ（並べ替えのときにそのまま送り返す）
    review_findings: dict[str, dict[str, str]] = {}  # review_id -> {aspect: polarity}
    explanations: dict[str, Explanation] = {}  # product_id -> 説明


class RecommendationResult(BaseModel):
    is_preview: bool = False
    status: Status
    status_message: str
    follow_up_questions: list[str] = []
    explanation_mode: Literal["llm", "template", "none"] = "none"
    data_version: str
    uses_dummy_data: bool = False
    plan_directions: list[DirectionView] = []
    owned_analysis: OwnedAnalysis | None = None
    candidates: list[CandidateView] = []
    recommended_product_id: str | None = None
    alternative_product_ids: list[str] = []
    ranking: Ranking | None = None
    routines: list[RoutinePlan] = []  # 先頭が今の棚、続いて候補ごと
    branch_status: dict[str, str] = {}
    missing: list[str] = []
    research_mode: Literal["live", "catalog", "catalog_fallback"] = "catalog"
    researched_at: str | None = None
    research_notes: list[str] = []
    search_suggestions_html: list[str] = []  # Google検索の検索候補（グラウンディングの表示要件）
    research_log: list[ResearchStep] = []
    analysis: Analysis = Analysis()


class RerankRequest(RecommendRequest):
    analysis: Analysis


class ProgressEvent(BaseModel):
    type: Literal["progress"] = "progress"
    node: str
    label: str
    status: Literal["running", "done", "failed", "skipped"]


class ResultEvent(BaseModel):
    type: Literal["result"] = "result"
    result: RecommendationResult
