"""数据模型：规定“一个景点、一次旅行必须有哪些字段”。

这里用 Pydantic 定义结构。好处是：数据不合格（比如缺经纬度、状态写错）会立刻报错，
以后让大模型输出数据时，也能用同样的结构去检查它有没有乱写。
"""

from __future__ import annotations

from datetime import date, timedelta
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# 枚举：一组固定的可选值
# ---------------------------------------------------------------------------

class PlaceStatus(str, Enum):
    """景点在这次旅行里的“确定程度”。"""

    IDEA = "idea"            # 想法：先记下来，暂不考虑安排
    SHORTLIST = "shortlist"  # 入围：打算去，等待分配到某一天
    PLANNED = "planned"      # 已安排：已经分配到某一天
    CONFIRMED = "confirmed"  # 已确认：用户明确拍板
    EXCLUDED = "excluded"    # 排除：不去了


# 参与自动分天的状态（idea 和 excluded 不参与）
SCHEDULABLE_STATUSES = {PlaceStatus.SHORTLIST, PlaceStatus.PLANNED, PlaceStatus.CONFIRMED}


class Pace(str, Enum):
    """旅行节奏：决定每天能排多少。"""

    RELAXED = "relaxed"  # 悠闲
    NORMAL = "normal"    # 正常
    PACKED = "packed"    # 紧凑


class DateMode(str, Enum):
    """日期的确定程度：先笼统，再慢慢收敛。"""

    UNKNOWN = "unknown"  # 还没定，只知道大概几天
    RANGE = "range"      # 只知道一个可选范围（最早出发 ~ 最晚返回）
    EXACT = "exact"      # 已确定具体起止日期


TravelMode = Literal["walk", "transit", "drive"]


# ---------------------------------------------------------------------------
# 基础对象
# ---------------------------------------------------------------------------

class Place(BaseModel):
    """一个想去的地点（景点、餐厅都可以）。"""

    id: str
    name: str
    lat: float = Field(ge=-90, le=90, description="纬度")
    lon: float = Field(ge=-180, le=180, description="经度")
    status: PlaceStatus = PlaceStatus.SHORTLIST
    duration_min: int = Field(default=90, ge=10, le=720, description="预计游览时长（分钟）")
    priority: int = Field(default=3, ge=1, le=5, description="重要程度 1~5，5 最重要")
    must_go: bool = Field(default=False, description="是否必去")
    ticket_price: float = Field(default=0, ge=0, description="门票（元）")
    closed_weekdays: list[int] = Field(
        default_factory=list, description="每周哪几天闭馆：0=周一 … 6=周日"
    )
    reservation_required: bool = False
    reserved: bool = Field(default=False, description="需要预约的话，是否已经约好")
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    source: str = Field(default="user", description="来源：user / agent / 某个网址等")
    opening_hours: str = Field(default="", description="营业时间原文（如高德返回的本周营业时间）")
    hours_source: str = Field(default="", description="营业时间的来源：amap / 官网网址 / user；空表示未核实")
    backups: list[str] = Field(default_factory=list, description="备选景点的 id：这个景点去不成（如没约上）时换成它们")

    @model_validator(mode="after")
    def _check_weekdays(self) -> "Place":
        for d in self.closed_weekdays:
            if d < 0 or d > 6:
                raise ValueError(f"closed_weekdays 里的数字必须在 0~6 之间，收到 {d}")
        return self


class Meal(BaseModel):
    """用户选定的用餐点：挂在某天某个景点之后。不占景点容量，不参与排程，信息来自地图服务。"""

    id: str
    day: int = Field(ge=0, description="第几天，从 0 开始")
    after_place_id: str = Field(description="挂在哪个景点之后（该景点附近）")
    name: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    address: str = ""
    cost_per_person: Optional[float] = Field(default=None, ge=0, description="人均消费参考（元），不是实时价")
    rating: Optional[float] = None
    opening_hours: str = ""
    hours_source: str = ""
    distance_m: Optional[int] = Field(default=None, description="离挂靠景点的直线距离（米）")
    source: str = "amap"


class Lodging(BaseModel):
    """候选住宿。"""

    id: str
    name: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    price_min: float = Field(default=0, ge=0, description="每晚最低价（元）")
    price_max: float = Field(default=0, ge=0, description="每晚最高价（元）")
    status: Literal["candidate", "booked"] = "candidate"
    notes: str = ""

    @property
    def price_mid(self) -> float:
        return (self.price_min + self.price_max) / 2


class Leg(BaseModel):
    """相邻两个停靠点之间的交通。

    detail_level 表示“细化程度”（对应我们之前讨论的三层）：
      estimate = 估算（直线距离换算，免费，随时重算）
      route    = 路线（调用地图服务得到的真实时长，里程碑 3 才会有）
      steps    = 详情（换乘步骤，最后才做）
    """

    from_id: str
    to_id: str
    mode: TravelMode
    distance_km: float
    minutes: int
    detail_level: Literal["estimate", "route", "steps"] = "estimate"
    path: list[list[float]] = Field(default_factory=list, description="真实路线形状 [[纬度,经度],…]，WGS84，已抽稀；估算没有")
    path_checked: bool = Field(default=False, description="是否已向地图服务请求过路线形状（旧缓存没有，会重新查一次）")
    note: str = Field(default="", description="路线说明，如公交的线路、换乘次数、步行距离、票价")


# ---------------------------------------------------------------------------
# 行程安排
# ---------------------------------------------------------------------------

class DayItem(BaseModel):
    """某一天里的一个条目（引用景点 id）。locked=True 表示用户锁定，程序不许动。"""

    place_id: str
    locked: bool = False


class DayPlan(BaseModel):
    index: int = Field(ge=0, description="第几天，从 0 开始")
    items: list[DayItem] = Field(default_factory=list)


class Unscheduled(BaseModel):
    """没能排进去的景点，以及原因。"""

    place_id: str
    reason: str


class Plan(BaseModel):
    days: list[DayPlan] = Field(default_factory=list)
    unscheduled: list[Unscheduled] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 旅行本身
# ---------------------------------------------------------------------------

class TransportPrefs(BaseModel):
    """出行偏好：用来在“步行 / 公交地铁 / 打车”之间给出建议（最终由用户选择）。"""

    walk_max_min: int = Field(default=20, ge=1, le=120, description="单段步行能接受的最长分钟数")
    prefer_subway: bool = Field(default=False, description="更愿意坐地铁")
    max_transfers: Optional[int] = Field(default=None, ge=0, le=5, description="公交/地铁最多换乘几次；不填不限")
    taxi_ok: bool = Field(default=True, description="是否接受打车")
    notes: str = Field(default="", description="其他说明，如带老人/小孩、行李多")


class TripMeta(BaseModel):
    name: str = "我的旅行"
    date_mode: DateMode = DateMode.UNKNOWN
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    earliest_start: Optional[date] = None
    latest_end: Optional[date] = None
    num_days: int = Field(default=3, ge=1, le=30)
    pace: Pace = Pace.NORMAL
    mode: TravelMode = "transit"
    budget_total: Optional[float] = Field(default=None, ge=0)
    travelers: int = Field(default=1, ge=1, le=50, description="出行人数（门票、餐饮按人数估算）")
    currency: str = "CNY"
    transport_prefs: TransportPrefs = Field(default_factory=TransportPrefs)

    @model_validator(mode="after")
    def _derive(self) -> "TripMeta":
        if self.date_mode == DateMode.EXACT:
            if not (self.start_date and self.end_date):
                raise ValueError("date_mode 为 exact 时，必须填写 start_date 和 end_date")
            if self.end_date < self.start_date:
                raise ValueError("end_date 不能早于 start_date")
            # 日期确定后，天数以日期为准
            self.num_days = (self.end_date - self.start_date).days + 1
        return self


class Trip(BaseModel):
    meta: TripMeta = Field(default_factory=TripMeta)
    places: list[Place] = Field(default_factory=list)
    lodgings: list[Lodging] = Field(default_factory=list)
    chosen_lodging_id: Optional[str] = None
    plan: Optional[Plan] = None
    revision: int = Field(default=0, description="版本号：每次改动 +1，用来防止过期的提案被误用")
    meals: list[Meal] = Field(default_factory=list, description="用户选定的用餐点")
    leg_modes: dict[str, TravelMode] = Field(
        default_factory=dict,
        description="单段出行方式：键是“起点id>终点id”，没有的段用 meta.mode",
    )
    route_overrides: dict[str, Leg] = Field(
        default_factory=dict,
        description="真实路线缓存（来自地图服务）。键见 metrics.leg_key；坐标变了键就变，旧缓存自动失效",
    )
    history: list[dict] = Field(default_factory=list, description="历史快照，用于撤销")

    @model_validator(mode="after")
    def _check_ids(self) -> "Trip":
        place_ids = [p.id for p in self.places]
        if len(place_ids) != len(set(place_ids)):
            raise ValueError("景点 id 不能重复")
        lodging_ids = [l.id for l in self.lodgings]
        if len(lodging_ids) != len(set(lodging_ids)):
            raise ValueError("住宿 id 不能重复")
        if self.chosen_lodging_id and self.chosen_lodging_id not in lodging_ids:
            raise ValueError(f"chosen_lodging_id 找不到对应的住宿：{self.chosen_lodging_id}")
        return self

    # ---- 一些方便的查询方法 ----

    def place(self, place_id: str) -> Place:
        for p in self.places:
            if p.id == place_id:
                return p
        raise KeyError(f"找不到景点：{place_id}")

    def day_date(self, index: int) -> Optional[date]:
        """第 index 天对应的日期；日期没定时返回 None。"""
        if self.meta.date_mode == DateMode.EXACT and self.meta.start_date:
            return self.meta.start_date + timedelta(days=index)
        return None

    @property
    def chosen_lodging(self) -> Optional[Lodging]:
        if not self.chosen_lodging_id:
            return None
        for l in self.lodgings:
            if l.id == self.chosen_lodging_id:
                return l
        return None
