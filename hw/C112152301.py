import base64
import calendar
import csv
import math
import re
import struct
import zlib
from collections import defaultdict
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox, filedialog


# ==========================================
# 純 Python 抗鋸齒圓環 PNG 渲染器（免安裝套件）
# ==========================================
def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _encode_rgb_png(width: int, height: int, rows: list[bytearray]) -> bytes:
    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack("!I", len(data))
            + tag
            + data
            + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    ihdr = struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw, 6))
        + _chunk(b"IEND", b"")
    )


def render_smooth_donut_photo(
    size: int,
    r_out: float,
    r_in: float,
    slices: list[tuple[float, float, str]],
    bg_hex: str = "#FFFFFF",
    gap_half: float = 0.9,
) -> tk.PhotoImage:
    """使用距離場抗鋸齒繪製平滑甜甜圈圖，回傳 Tkinter PhotoImage"""
    cx = cy = size / 2.0
    bg_r, bg_g, bg_b = _hex_to_rgb(bg_hex)
    bg_row = bytes((bg_r, bg_g, bg_b)) * size

    r_out_p = r_out + 1.0
    r_out_p2 = r_out_p * r_out_p
    r_in_m = max(0.0, r_in - 1.0)
    r_in_m2 = r_in_m * r_in_m

    rgb_slices = [(a0, a1, _hex_to_rgb(col)) for a0, a1, col in slices]
    has_gaps = len(rgb_slices) > 1
    rows: list[bytearray] = []

    for y in range(size):
        dy = y + 0.5 - cy
        dy2 = dy * dy
        row = bytearray(bg_row)

        if dy2 < r_out_p2 and rgb_slices:
            max_dx = math.sqrt(r_out_p2 - dy2)
            x_start = max(0, int(cx - max_dx))
            x_end = min(size, int(cx + max_dx) + 1)

            for x in range(x_start, x_end):
                dx = x + 0.5 - cx
                d2 = dx * dx + dy2
                if d2 < r_in_m2 or d2 > r_out_p2:
                    continue

                dist = math.sqrt(d2)
                c_out = r_out - dist + 0.5
                if c_out <= 0.0:
                    continue
                if c_out > 1.0:
                    c_out = 1.0

                c_in = dist - r_in + 0.5
                if c_in <= 0.0:
                    continue
                if c_in > 1.0:
                    c_in = 1.0

                alpha = c_out * c_in

                if has_gaps:
                    angle = math.degrees(math.atan2(dx, -dy)) % 360.0
                    s_deg, e_deg, (sr, sg, sb) = rgb_slices[-1]
                    for a0, a1, rgb in rgb_slices:
                        if a0 <= angle < a1:
                            s_deg, e_deg = a0, a1
                            sr, sg, sb = rgb
                            break

                    d1 = angle - s_deg
                    d2_ang = e_deg - angle
                    min_ang = d1 if d1 < d2_ang else d2_ang
                    if min_ang < 35.0:
                        edge_dist = dist * math.sin(math.radians(min_ang))
                        c_gap = edge_dist - gap_half + 0.5
                        if c_gap <= 0.0:
                            continue
                        if c_gap < 1.0:
                            alpha *= c_gap
                else:
                    sr, sg, sb = rgb_slices[0][2]

                idx = x * 3
                row[idx] = int(bg_r + (sr - bg_r) * alpha + 0.5)
                row[idx + 1] = int(bg_g + (sg - bg_g) * alpha + 0.5)
                row[idx + 2] = int(bg_b + (sb - bg_b) * alpha + 0.5)

        rows.append(row)

    png_bytes = _encode_rgb_png(size, size, rows)
    return tk.PhotoImage(data=base64.b64encode(png_bytes).decode("ascii"))


# ==========================================
# 核心物件導向類別（Category / Transaction / Account）
# ==========================================
class Category:
    """收支類別（含圖示、柔和色塊與每月預算上限）"""
    def __init__(self, name: str, monthly_budget: float = 0.0, icon: str = "📌", color: str = "#A7AEB8"):
        self.name = name
        self.monthly_budget = monthly_budget
        self.icon = icon
        self.color = color

    def set_monthly_budget(self, budget: float):
        self.monthly_budget = budget


class Transaction:
    """單筆收支紀錄"""
    def __init__(self, date: str, trans_type: str, category: Category, amount: float, note: str = ""):
        self.date = date              # YYYY-MM-DD
        self.trans_type = trans_type  # "支出" 或 "收入"
        self.category = category
        self.amount = amount
        self.note = note

    def get_month(self) -> str:
        return self.date[:7] if len(self.date) >= 7 else "未知月份"

    def to_csv_row(self) -> list:
        return [self.date, self.trans_type, self.category.name, self.amount, self.note]


class Account:
    """帳戶管理、收支統計、預算警告、常用標籤記憶與 CSV 匯出"""
    def __init__(self, account_name: str):
        self.account_name = account_name
        self.transactions: list[Transaction] = []
        self.categories: dict[str, Category] = {
            "飲食": Category("飲食", 6000, "🍔", "#D9A97E"),
            "飲料": Category("飲料", 1500, "🧋", "#D4A3B0"),
            "交通": Category("交通", 1500, "🚇", "#8FAEC6"),
            "娛樂": Category("娛樂", 2000, "🎮", "#AFA1C4"),
            "日用": Category("日用", 1500, "🛒", "#8FBAB0"),
            "購物": Category("購物", 2500, "🛍️", "#D8C388"),
            "薪資": Category("薪資", 0, "💰", "#8CB39A"),
            "其他": Category("其他", 0, "📌", "#A6ACB5"),
        }
        self.category_tags: dict[str, list[str]] = {
            "飲食": ["早餐", "午餐", "晚餐", "麥當勞", "聚餐"],
            "飲料": ["手搖飲", "咖啡", "超商飲料"],
            "交通": ["台鐵", "捷運", "加油"],
            "娛樂": ["遊戲儲值", "電影", "訂閱費"],
            "日用": ["全聯", "日用品"],
            "購物": ["網購", "服飾"],
            "薪資": ["打工薪水", "零用錢", "獎學金"],
            "其他": ["雜支"],
        }

    def get_or_create_category(self, name: str) -> Category:
        name = name.strip() or "其他"
        if name not in self.categories:
            self.categories[name] = Category(name, 0, "🏷️", "#9EA8BD")
        return self.categories[name]

    def set_category_budget(self, name: str, budget: float):
        cat = self.get_or_create_category(name)
        cat.set_monthly_budget(budget)

    def get_tags_for_category(self, cat_name: str) -> list[str]:
        return self.category_tags.get(cat_name, [])[:6]

    def add_transaction(self, t: Transaction) -> str | None:
        self.transactions.append(t)
        self.transactions.sort(key=lambda x: x.date, reverse=True)

        if t.note:
            tags = self.category_tags.setdefault(t.category.name, [])
            if t.note not in tags:
                tags.insert(0, t.note)

        if t.trans_type == "支出":
            return self.check_budget_warning(t.category, t.get_month())
        return None

    def delete_transaction(self, target: Transaction):
        if target in self.transactions:
            self.transactions.remove(target)

    def check_budget_warning(self, category: Category, month: str) -> str | None:
        budget = category.monthly_budget
        if budget <= 0:
            return None
        spent = sum(
            t.amount for t in self.transactions
            if t.trans_type == "支出" and t.category.name == category.name and t.get_month() == month
        )
        if spent > budget:
            over = spent - budget
            return f"{month}「{category.name}」已花費 ${spent:,.0f}，超過預算 ${budget:,.0f}（超支 ${over:,.0f}）！"
        return None

    def get_filtered_transactions(self, month: str = "全部", keyword: str = "") -> list[Transaction]:
        rows = self.transactions if (not month or month == "全部") else [t for t in self.transactions if t.get_month() == month]
        kw = keyword.strip().lower()
        if kw:
            rows = [t for t in rows if kw in t.category.name.lower() or kw in t.note.lower() or kw in t.date]
        return list(rows)

    def get_summary(self, month: str = "全部") -> tuple[float, float, float]:
        rows = self.get_filtered_transactions(month)
        income = sum(t.amount for t in rows if t.trans_type == "收入")
        expense = sum(t.amount for t in rows if t.trans_type == "支出")
        return income, expense, income - expense

    def get_category_expenses(self, month: str = "全部") -> dict[str, float]:
        totals = defaultdict(float)
        for t in self.get_filtered_transactions(month):
            if t.trans_type == "支出":
                totals[t.category.name] += t.amount
        return dict(totals)

    def get_daily_totals(self, month: str) -> dict[int, tuple[float, float]]:
        daily = defaultdict(lambda: [0.0, 0.0])
        for t in self.transactions:
            if t.get_month() == month and len(t.date) >= 10:
                try:
                    day = int(t.date[8:10])
                    if t.trans_type == "收入":
                        daily[day][0] += t.amount
                    else:
                        daily[day][1] += t.amount
                except ValueError:
                    pass
        return {d: (vals[0], vals[1]) for d, vals in daily.items()}

    def load_sample_data(self):
        ym = datetime.today().strftime("%Y-%m")
        samples = [
            (f"{ym}-01", "收入", "薪資", 20000, "打工薪水"),
            (f"{ym}-03", "支出", "飲食", 165, "麥當勞"),
            (f"{ym}-05", "支出", "交通", 450, "台鐵"),
            (f"{ym}-08", "支出", "飲料", 70, "手搖飲"),
            (f"{ym}-12", "支出", "娛樂", 1490, "遊戲儲值"),
            (f"{ym}-15", "支出", "日用", 680, "全聯"),
            (f"{ym}-18", "支出", "飲食", 980, "聚餐"),
        ]
        for date, t_type, cat_name, amt, note in samples:
            self.add_transaction(Transaction(date, t_type, self.get_or_create_category(cat_name), amt, note))

    def export_to_csv(self, filename: str):
        with open(filename, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["日期", "類型", "類別", "金額", "備註"])
            for t in self.transactions:
                writer.writerow(t.to_csv_row())


# ==========================================
# 柔和低飽和版《簡單記帳》風格 UI
# ==========================================
class SimpleAccountingApp:
    BG_PAPER = "#F5F4F0"
    CARD_BG = "#FFFFFF"
    INK = "#3A3E45"
    BORDER = "#787E87"
    SUBTEXT = "#6E747E"

    YELLOW = "#E6D3A3"
    YELLOW_SOFT = "#FAF6EA"
    BLUE = "#B8CEDE"
    BLUE_SOFT = "#EFF4F8"
    RED = "#D99595"
    RED_SOFT = "#F8ECEC"
    RED_TEXT = "#A84A4A"
    GREEN = "#BAD2C0"
    NEUTRAL = "#ECECE8"

    CAL_EXP_TEXT = "#9B5E2E"
    CAL_INC_TEXT = "#2F6B88"

    DONUT_SIZE = 228
    DONUT_R_OUT = 98.0
    DONUT_R_IN = 62.0

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("個人記帳與預算分析工具")
        self.root.geometry("1120x690")
        self.root.minsize(980, 620)
        self.root.configure(bg=self.BG_PAPER)

        self.account = Account("我的個人帳本")

        self.f_xs = ("Microsoft JhengHei UI", 8)
        self.f_sm = ("Microsoft JhengHei UI", 9)
        self.f_sm_b = ("Microsoft JhengHei UI", 9, "bold")
        self.f_md = ("Microsoft JhengHei UI", 10)
        self.f_md_b = ("Microsoft JhengHei UI", 10, "bold")
        self.f_lg_b = ("Microsoft JhengHei UI", 12, "bold")
        self.f_xl_b = ("Microsoft JhengHei UI", 17, "bold")

        # 月曆專用大字體
        self.f_cal_head = ("Microsoft JhengHei UI", 11, "bold")
        self.f_cal_day = ("Microsoft JhengHei UI", 13, "bold")
        self.f_cal_amt = ("Microsoft JhengHei UI", 11, "bold")
        self.f_cal_amt_sm = ("Microsoft JhengHei UI", 10, "bold")

        self.current_month = datetime.today().strftime("%Y-%m")
        self.show_all_months = False
        self.active_tab = "records"
        self.editing_budget_cat: str | None = None
        self._inline_budget_var: tk.StringVar | None = None

        self._donut_photo: tk.PhotoImage | None = None
        self._donut_hit_slices: list[tuple[float, float, str, str, float, float]] = []
        self._donut_total: float = 0.0
        self._donut_text_ids: tuple[int, int, int] | None = None

        self.trans_type_var = tk.StringVar(value="支出")
        self.category_var = tk.StringVar(value="飲食")
        self.date_var = tk.StringVar(value=datetime.today().strftime("%Y-%m-%d"))
        self.amount_var = tk.StringVar(value="")
        self.note_var = tk.StringVar(value="")
        self.search_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="就緒：點選右側分類與數字鍵盤開始記帳，或按上方「✨ 範例資料」預覽。")

        self._setup_styles()
        self._build_layout()
        self._select_type("支出")
        self._select_category("飲食")
        self._refresh_all()

    def _card_box(self, parent, bg="#FFFFFF", width=None):
        kwargs = dict(bg=bg, highlightbackground=self.BORDER, highlightcolor=self.BORDER, highlightthickness=1, bd=0)
        if width is not None:
            kwargs["width"] = width
        return tk.Frame(parent, **kwargs)

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Soft.Treeview",
            font=self.f_md,
            rowheight=30,
            background="#FFFFFF",
            fieldbackground="#FFFFFF",
            borderwidth=0,
        )
        style.configure(
            "Soft.Treeview.Heading",
            font=self.f_sm_b,
            background=self.NEUTRAL,
            foreground=self.INK,
            relief="flat",
        )
        style.map("Soft.Treeview", background=[("selected", "#E9E3D2")], foreground=[("selected", self.INK)])

    def _build_layout(self):
        topbar = tk.Frame(self.root, bg=self.BG_PAPER)
        topbar.pack(fill="x", padx=18, pady=(10, 6))

        tk.Button(
            topbar, text="📤 匯出 CSV", font=self.f_sm_b, bg=self.GREEN, fg=self.INK,
            activebackground="#A9C5B0", bd=1, relief="solid", cursor="hand2",
            padx=12, pady=3, command=self.handle_export_csv,
        ).pack(side="right")

        tk.Button(
            topbar, text="✨ 範例資料", font=self.f_sm_b, bg="#FFFFFF", fg=self.INK,
            activebackground=self.NEUTRAL, bd=1, relief="solid", cursor="hand2",
            padx=12, pady=3, command=self.handle_load_sample,
        ).pack(side="right", padx=(0, 8))

        body = tk.Frame(self.root, bg=self.BG_PAPER)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 6))

        self.left_col = tk.Frame(body, bg=self.BG_PAPER)
        self.left_col.pack(side="left", fill="both", expand=True, padx=(0, 14))

        self.right_col = self._card_box(body, bg="#FFFFFF", width=395)
        self.right_col.pack(side="right", fill="y")
        self.right_col.pack_propagate(False)

        self._build_left_panel()
        self._build_right_panel()

        status_bar = tk.Frame(self.root, bg=self.BG_PAPER)
        status_bar.pack(fill="x", padx=18, pady=(0, 8))
        tk.Label(status_bar, textvariable=self.status_var, font=self.f_sm,
                 bg=self.BG_PAPER, fg=self.SUBTEXT, anchor="w").pack(fill="x")

    # ==========================================
    # 左側：柔和總覽卡 + 四大分頁（明細/月曆/報表/預算）
    # ==========================================
    def _build_left_panel(self):
        summary = self._card_box(self.left_col, bg="#FFFFFF")
        summary.pack(fill="x", pady=(0, 10))

        inner = tk.Frame(summary, bg="#FFFFFF", padx=14, pady=10)
        inner.pack(fill="x")

        m_row = tk.Frame(inner, bg="#FFFFFF")
        m_row.pack(fill="x")

        tk.Button(m_row, text="◀", font=self.f_sm_b, bg=self.NEUTRAL, fg=self.INK,
                  bd=1, relief="solid", cursor="hand2", width=3,
                  command=lambda: self._shift_month(-1)).pack(side="left")
        self.month_lbl = tk.Label(m_row, text=self.current_month, font=self.f_lg_b,
                                  bg="#FFFFFF", fg=self.INK, width=10)
        self.month_lbl.pack(side="left", padx=4)
        tk.Button(m_row, text="▶", font=self.f_sm_b, bg=self.NEUTRAL, fg=self.INK,
                  bd=1, relief="solid", cursor="hand2", width=3,
                  command=lambda: self._shift_month(1)).pack(side="left")

        self.all_month_btn = tk.Button(
            m_row, text="全部月份", font=self.f_sm, bg="#FFFFFF", fg=self.INK,
            bd=1, relief="solid", cursor="hand2", padx=8, command=self._toggle_all_months,
        )
        self.all_month_btn.pack(side="left", padx=(8, 0))

        self.ratio_hint_lbl = tk.Label(m_row, text="米黃＝支出 ｜ 霧藍＝收入", font=self.f_xs,
                                       bg=self.NEUTRAL, fg=self.SUBTEXT, padx=8, pady=2)
        self.ratio_hint_lbl.pack(side="right")

        cards_row = tk.Frame(inner, bg="#FFFFFF")
        cards_row.pack(fill="x", pady=(10, 8))
        for i in range(3):
            cards_row.columnconfigure(i, weight=1, uniform="stat")

        exp_box = self._card_box(cards_row, bg=self.YELLOW_SOFT)
        exp_box.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        tk.Label(exp_box, text="支出", font=self.f_sm_b, bg=self.YELLOW_SOFT, fg=self.SUBTEXT).pack(anchor="w", padx=10, pady=(5, 0))
        self.expense_lbl = tk.Label(exp_box, text="$0", font=self.f_xl_b, bg=self.YELLOW_SOFT, fg=self.INK)
        self.expense_lbl.pack(anchor="w", padx=10, pady=(0, 5))

        inc_box = self._card_box(cards_row, bg=self.BLUE_SOFT)
        inc_box.grid(row=0, column=1, sticky="ew", padx=3)
        tk.Label(inc_box, text="收入", font=self.f_sm_b, bg=self.BLUE_SOFT, fg=self.SUBTEXT).pack(anchor="w", padx=10, pady=(5, 0))
        self.income_lbl = tk.Label(inc_box, text="$0", font=self.f_xl_b, bg=self.BLUE_SOFT, fg=self.INK)
        self.income_lbl.pack(anchor="w", padx=10, pady=(0, 5))

        self.bal_box = self._card_box(cards_row, bg="#FFFFFF")
        self.bal_box.grid(row=0, column=2, sticky="ew", padx=(6, 0))
        self.bal_title_lbl = tk.Label(self.bal_box, text="本期結餘", font=self.f_sm_b, bg="#FFFFFF", fg=self.SUBTEXT)
        self.bal_title_lbl.pack(anchor="w", padx=10, pady=(5, 0))
        self.balance_lbl = tk.Label(self.bal_box, text="$0", font=self.f_xl_b, bg="#FFFFFF", fg=self.INK)
        self.balance_lbl.pack(anchor="w", padx=10, pady=(0, 5))

        bar_wrap = self._card_box(inner, bg=self.NEUTRAL)
        bar_wrap.pack(fill="x")
        self.ratio_canvas = tk.Canvas(bar_wrap, height=13, bg=self.NEUTRAL, highlightthickness=0)
        self.ratio_canvas.pack(fill="x")
        self.ratio_canvas.bind("<Configure>", lambda _e: self._draw_ratio_bar())
        self._last_inc = 0.0
        self._last_exp = 0.0

        tab_bar = tk.Frame(self.left_col, bg=self.BG_PAPER)
        tab_bar.pack(fill="x", pady=(0, 8))
        for i in range(4):
            tab_bar.columnconfigure(i, weight=1, uniform="tabs")

        self.tab_buttons = {}
        tab_defs = [
            ("records", "📋 明細"),
            ("calendar", "📅 月曆"),
            ("charts", "📊 報表"),
            ("budgets", "🎯 預算"),
        ]
        for idx, (key, text) in enumerate(tab_defs):
            btn = tk.Button(
                tab_bar, text=text, font=self.f_md_b, bd=1, relief="solid",
                cursor="hand2", pady=5, command=lambda k=key: self._switch_tab(k),
            )
            btn.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 6, 0))
            self.tab_buttons[key] = btn

        self.content_card = self._card_box(self.left_col, bg="#FFFFFF")
        self.content_card.pack(fill="both", expand=True)

        self.tab_frames = {
            "records": tk.Frame(self.content_card, bg="#FFFFFF"),
            "calendar": tk.Frame(self.content_card, bg="#FFFFFF"),
            "charts": tk.Frame(self.content_card, bg="#FFFFFF"),
            "budgets": tk.Frame(self.content_card, bg="#FFFFFF"),
        }
        self._build_records_tab(self.tab_frames["records"])
        self._build_calendar_tab(self.tab_frames["calendar"])
        self._build_charts_tab(self.tab_frames["charts"])
        self._build_budgets_tab(self.tab_frames["budgets"])
        self._switch_tab("records")

    def _build_records_tab(self, parent: tk.Frame):
        top = tk.Frame(parent, bg="#FFFFFF", padx=12, pady=8)
        top.pack(fill="x")

        tk.Label(top, text="🔍 搜尋：", font=self.f_sm_b, bg="#FFFFFF", fg=self.INK).pack(side="left")
        search_entry = tk.Entry(top, textvariable=self.search_var, font=self.f_sm, width=18, bd=1, relief="solid")
        search_entry.pack(side="left", ipady=2)
        self.search_var.trace_add("write", lambda *_args: self._refresh_records_table())

        self.record_count_lbl = tk.Label(top, text="共 0 筆", font=self.f_sm, bg="#FFFFFF", fg=self.SUBTEXT)
        self.record_count_lbl.pack(side="left", padx=(10, 0))

        tk.Button(
            top, text="🗑 刪除選取", font=self.f_sm, bg=self.RED_SOFT, fg=self.RED_TEXT,
            bd=1, relief="solid", cursor="hand2", padx=8, pady=1, command=self.handle_delete_selected,
        ).pack(side="right")

        wrap = tk.Frame(parent, bg="#FFFFFF", padx=12)
        wrap.pack(fill="both", expand=True, pady=(0, 10))

        cols = ("date", "type", "category", "note", "amount")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", style="Soft.Treeview")
        self.tree.heading("date", text="日期")
        self.tree.heading("type", text="類型")
        self.tree.heading("category", text="分類")
        self.tree.heading("note", text="備註標籤")
        self.tree.heading("amount", text="金額")

        self.tree.column("date", width=98, anchor="center")
        self.tree.column("type", width=55, anchor="center")
        self.tree.column("category", width=95, anchor="w")
        self.tree.column("note", width=180, anchor="w")
        self.tree.column("amount", width=100, anchor="e")

        self.tree.tag_configure("expense", background=self.YELLOW_SOFT, foreground=self.INK)
        self.tree.tag_configure("income", background=self.BLUE_SOFT, foreground=self.INK)

        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _build_calendar_tab(self, parent: tk.Frame):
        top = tk.Frame(parent, bg="#FFFFFF", padx=12, pady=8)
        top.pack(fill="x")
        self.cal_title_lbl = tk.Label(top, text="月曆收支總覽（點選日期即可切換右側記帳日期）",
                                      font=self.f_md_b, bg="#FFFFFF", fg=self.INK)
        self.cal_title_lbl.pack(side="left")

        self.cal_grid_frame = tk.Frame(parent, bg="#FFFFFF", padx=10)
        self.cal_grid_frame.pack(fill="both", expand=True, pady=(0, 10))

    def _build_charts_tab(self, parent: tk.Frame):
        container = tk.Frame(parent, bg="#FFFFFF", padx=14, pady=12)
        container.pack(fill="both", expand=True)

        left_chart = tk.Frame(container, bg="#FFFFFF")
        left_chart.pack(side="left", padx=(4, 16), anchor="n")

        self.donut_canvas = tk.Canvas(
            left_chart,
            width=self.DONUT_SIZE,
            height=self.DONUT_SIZE,
            bg="#FFFFFF",
            highlightthickness=0,
        )
        self.donut_canvas.pack()
        self.donut_canvas.bind("<Motion>", self._on_donut_hover)
        self.donut_canvas.bind("<Leave>", self._on_donut_leave)

        tk.Label(
            left_chart,
            text="滑鼠移到色塊可查看單項明細",
            font=self.f_xs,
            bg="#FFFFFF",
            fg=self.SUBTEXT,
        ).pack(pady=(2, 0))

        self.chart_legend_frame = tk.Frame(container, bg="#FFFFFF")
        self.chart_legend_frame.pack(side="left", fill="both", expand=True, pady=(4, 0))

    def _build_budgets_tab(self, parent: tk.Frame):
        top = tk.Frame(parent, bg="#FFFFFF", padx=14, pady=8)
        top.pack(fill="x")
        tk.Label(top, text="各分類每月預算（點「調整」可直接在卡片內修改，支援滾輪捲動）", font=self.f_sm_b,
                 bg="#FFFFFF", fg=self.INK).pack(side="left")

        scroll_wrap = tk.Frame(parent, bg="#FFFFFF", padx=12)
        scroll_wrap.pack(fill="both", expand=True, pady=(0, 10))

        self.budget_canvas = tk.Canvas(scroll_wrap, bg="#FFFFFF", highlightthickness=0)
        self.budget_scrollbar = ttk.Scrollbar(scroll_wrap, orient="vertical", command=self.budget_canvas.yview)
        self.budget_canvas.configure(yscrollcommand=self.budget_scrollbar.set)

        self.budget_scrollbar.pack(side="right", fill="y")
        self.budget_canvas.pack(side="left", fill="both", expand=True)

        self.budget_list_frame = tk.Frame(self.budget_canvas, bg="#FFFFFF")
        self.budget_window_id = self.budget_canvas.create_window((0, 0), window=self.budget_list_frame, anchor="nw")

        self.budget_list_frame.bind(
            "<Configure>",
            lambda _e: self.budget_canvas.configure(scrollregion=self.budget_canvas.bbox("all")),
        )
        self.budget_canvas.bind(
            "<Configure>",
            lambda e: self.budget_canvas.itemconfigure(self.budget_window_id, width=e.width),
        )

        self.budget_canvas.bind("<Enter>", self._bind_budget_wheel)
        self.budget_canvas.bind("<Leave>", self._unbind_budget_wheel)

    def _bind_budget_wheel(self, _event=None):
        self.root.bind_all("<MouseWheel>", self._on_budget_mousewheel)

    def _unbind_budget_wheel(self, _event=None):
        self.root.unbind_all("<MouseWheel>")

    def _on_budget_mousewheel(self, event):
        if self.active_tab == "budgets":
            self.budget_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ==========================================
    # 右側：快速記帳面板（柔和色票 + 計算機）
    # ==========================================
    def _build_right_panel(self):
        type_bar = tk.Frame(self.right_col, bg="#FFFFFF", padx=14, pady=10)
        type_bar.pack(fill="x")
        type_bar.columnconfigure(0, weight=1, uniform="t")
        type_bar.columnconfigure(1, weight=1, uniform="t")

        self.btn_expense = tk.Button(
            type_bar, text="支出", font=self.f_lg_b, bd=1, relief="solid",
            cursor="hand2", pady=4, command=lambda: self._select_type("支出"),
        )
        self.btn_expense.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.btn_income = tk.Button(
            type_bar, text="收入", font=self.f_lg_b, bd=1, relief="solid",
            cursor="hand2", pady=4, command=lambda: self._select_type("收入"),
        )
        self.btn_income.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.amt_box = self._card_box(self.right_col, bg=self.YELLOW_SOFT)
        self.amt_box.pack(fill="x", padx=14, pady=(0, 8))

        amt_top = tk.Frame(self.amt_box, bg=self.YELLOW_SOFT)
        amt_top.pack(fill="x", padx=10, pady=(6, 0))
        self.amt_top_frame = amt_top

        self.amt_cat_badge = tk.Label(amt_top, text="🍔 飲食", font=self.f_sm_b,
                                      bg=self.YELLOW, fg=self.INK, bd=1, relief="solid", padx=6, pady=1)
        self.amt_cat_badge.pack(side="left")

        self.amt_tip_lbl = tk.Label(amt_top, text="可打字或按計算機（支援 + -）",
                                    font=self.f_xs, bg=self.YELLOW_SOFT, fg=self.SUBTEXT)
        self.amt_tip_lbl.pack(side="right")

        amt_row = tk.Frame(self.amt_box, bg=self.YELLOW_SOFT)
        amt_row.pack(fill="x", padx=10, pady=(2, 6))
        self.amt_row_frame = amt_row

        self.dollar_lbl = tk.Label(amt_row, text="$", font=("Microsoft JhengHei UI", 18, "bold"),
                                   bg=self.YELLOW_SOFT, fg=self.INK)
        self.dollar_lbl.pack(side="left")

        self.amount_entry = tk.Entry(
            amt_row, textvariable=self.amount_var, font=("Microsoft JhengHei UI", 20, "bold"),
            bg=self.YELLOW_SOFT, fg=self.INK, bd=0, justify="right",
        )
        self.amount_entry.pack(side="left", fill="x", expand=True)
        self.amount_entry.bind("<Return>", lambda _e: self.handle_add_transaction())

        grid_wrap = tk.Frame(self.right_col, bg="#FFFFFF", padx=14)
        grid_wrap.pack(fill="x", pady=(0, 6))
        for c in range(4):
            grid_wrap.columnconfigure(c, weight=1, uniform="cat")

        self.cat_tiles = {}
        preset_cats = ["飲食", "飲料", "交通", "娛樂", "日用", "購物", "薪資", "其他"]
        for idx, name in enumerate(preset_cats):
            cat = self.account.categories[name]
            r, c = divmod(idx, 4)
            btn = tk.Button(
                grid_wrap, text=f"{cat.icon}\n{cat.name}", font=self.f_sm_b,
                bg="#FFFFFF", fg=self.INK, bd=1, relief="solid", cursor="hand2", pady=4,
                command=lambda n=name: self._select_category(n),
            )
            btn.grid(row=r, column=c, sticky="ew", padx=3, pady=3)
            self.cat_tiles[name] = btn

        meta = tk.Frame(self.right_col, bg="#FFFFFF", padx=14)
        meta.pack(fill="x", pady=(2, 4))

        r_date = tk.Frame(meta, bg="#FFFFFF")
        r_date.pack(fill="x", pady=2)
        tk.Label(r_date, text="日期", font=self.f_sm_b, bg="#FFFFFF", fg=self.INK, width=4, anchor="w").pack(side="left")
        tk.Button(r_date, text="◀", font=self.f_sm, bg=self.NEUTRAL, fg=self.INK, bd=1, relief="solid",
                  cursor="hand2", width=2, command=lambda: self._shift_date(-1)).pack(side="left")
        tk.Entry(r_date, textvariable=self.date_var, font=self.f_sm, width=11, justify="center",
                 bd=1, relief="solid").pack(side="left", padx=3, ipady=1)
        tk.Button(r_date, text="▶", font=self.f_sm, bg=self.NEUTRAL, fg=self.INK, bd=1, relief="solid",
                  cursor="hand2", width=2, command=lambda: self._shift_date(1)).pack(side="left")

        tk.Label(r_date, text="分類", font=self.f_sm_b, bg="#FFFFFF", fg=self.INK).pack(side="left", padx=(10, 4))
        tk.Entry(r_date, textvariable=self.category_var, font=self.f_sm, width=10, bd=1, relief="solid").pack(
            side="left", fill="x", expand=True, ipady=1
        )

        r_note = tk.Frame(meta, bg="#FFFFFF")
        r_note.pack(fill="x", pady=(4, 2))
        tk.Label(r_note, text="備註", font=self.f_sm_b, bg="#FFFFFF", fg=self.INK, width=4, anchor="w").pack(side="left")
        tk.Entry(r_note, textvariable=self.note_var, font=self.f_sm, bd=1, relief="solid").pack(
            side="left", fill="x", expand=True, ipady=2
        )

        self.tag_chips_frame = tk.Frame(self.right_col, bg="#FFFFFF", padx=14)
        self.tag_chips_frame.pack(fill="x", pady=(2, 6))

        pad = tk.Frame(self.right_col, bg="#FFFFFF", padx=14)
        pad.pack(fill="both", expand=True, pady=(0, 12))
        for c in range(4):
            pad.columnconfigure(c, weight=1, uniform="pad")
        for r in range(5):
            pad.rowconfigure(r, weight=1, uniform="pad")

        top_keys = [("C", self.RED_SOFT), ("+50", self.NEUTRAL), ("+100", self.NEUTRAL), ("⌫", self.RED_SOFT)]
        for c, (k, bg_c) in enumerate(top_keys):
            fg_c = self.RED_TEXT if bg_c == self.RED_SOFT else self.INK
            tk.Button(
                pad, text=k, font=self.f_md_b, bg=bg_c, fg=fg_c,
                bd=1, relief="solid", cursor="hand2",
                command=lambda key=k: self._on_keypad(key),
            ).grid(row=0, column=c, sticky="nsew", padx=2, pady=2)

        num_rows = [
            ("7", "8", "9", "+"),
            ("4", "5", "6", "-"),
            ("1", "2", "3", "="),
        ]
        for r_idx, row_keys in enumerate(num_rows, start=1):
            for c_idx, key in enumerate(row_keys):
                bg_c = self.NEUTRAL if key in ("+", "-", "=") else "#FFFFFF"
                tk.Button(
                    pad, text=key, font=self.f_lg_b, bg=bg_c, fg=self.INK,
                    activebackground=self.YELLOW_SOFT, bd=1, relief="solid", cursor="hand2",
                    command=lambda k=key: self._on_keypad(k),
                ).grid(row=r_idx, column=c_idx, sticky="nsew", padx=2, pady=2)

        for c_idx, key in enumerate(("00", "0", ".")):
            tk.Button(
                pad, text=key, font=self.f_lg_b, bg="#FFFFFF", fg=self.INK,
                activebackground=self.YELLOW_SOFT, bd=1, relief="solid", cursor="hand2",
                command=lambda k=key: self._on_keypad(k),
            ).grid(row=4, column=c_idx, sticky="nsew", padx=2, pady=2)

        self.ok_btn = tk.Button(
            pad, text="OK", font=("Microsoft JhengHei UI", 13, "bold"),
            bg=self.YELLOW, fg=self.INK, activebackground="#D9C38F",
            bd=1, relief="solid", cursor="hand2", command=self.handle_add_transaction,
        )
        self.ok_btn.grid(row=4, column=3, sticky="nsew", padx=2, pady=2)

    # ==========================================
    # 互動控制邏輯
    # ==========================================
    def _switch_tab(self, key: str):
        self.active_tab = key
        for k, frame in self.tab_frames.items():
            frame.pack_forget()
        self.tab_frames[key].pack(fill="both", expand=True)

        for k, btn in self.tab_buttons.items():
            if k == key:
                btn.configure(bg=self.YELLOW, fg=self.INK)
            else:
                btn.configure(bg="#FFFFFF", fg=self.SUBTEXT)
        self._refresh_all()

    def _select_type(self, trans_type: str):
        self.trans_type_var.set(trans_type)
        if trans_type == "支出":
            self.btn_expense.configure(bg=self.YELLOW, fg=self.INK)
            self.btn_income.configure(bg="#FFFFFF", fg=self.SUBTEXT)
            theme_bg, accent = self.YELLOW_SOFT, self.YELLOW
            if self.category_var.get() == "薪資":
                self._select_category("飲食")
        else:
            self.btn_income.configure(bg=self.BLUE, fg=self.INK)
            self.btn_expense.configure(bg="#FFFFFF", fg=self.SUBTEXT)
            theme_bg, accent = self.BLUE_SOFT, self.BLUE
            self._select_category("薪資")

        for w in (self.amt_box, self.amt_top_frame, self.amt_tip_lbl, self.amt_row_frame, self.dollar_lbl, self.amount_entry):
            w.configure(bg=theme_bg)
        self.ok_btn.configure(bg=accent)

    def _select_category(self, name: str):
        self.category_var.set(name)
        cat = self.account.get_or_create_category(name)
        self.amt_cat_badge.configure(text=f"{cat.icon} {cat.name}", bg=cat.color, fg="#FFFFFF")

        for n, btn in self.cat_tiles.items():
            c_obj = self.account.categories[n]
            if n == name:
                btn.configure(bg=c_obj.color, fg="#FFFFFF")
            else:
                btn.configure(bg="#FFFFFF", fg=self.INK)

        self._render_tag_chips(name)

    def _render_tag_chips(self, cat_name: str):
        for w in self.tag_chips_frame.winfo_children():
            w.destroy()
        tags = self.account.get_tags_for_category(cat_name)
        if not tags:
            return
        tk.Label(self.tag_chips_frame, text="常用：", font=self.f_xs, bg="#FFFFFF", fg=self.SUBTEXT).pack(side="left")
        for tag in tags[:5]:
            tk.Button(
                self.tag_chips_frame, text=f"#{tag}", font=self.f_xs,
                bg=self.BG_PAPER, fg=self.INK, bd=1, relief="solid",
                cursor="hand2", padx=5, pady=1,
                command=lambda t=tag: self.note_var.set(t),
            ).pack(side="left", padx=2)

    def _shift_month(self, delta: int):
        self.show_all_months = False
        y, m = map(int, self.current_month.split("-"))
        m += delta
        if m < 1:
            y, m = y - 1, 12
        elif m > 12:
            y, m = y + 1, 1
        self.current_month = f"{y:04d}-{m:02d}"
        self._refresh_all()

    def _toggle_all_months(self):
        self.show_all_months = not self.show_all_months
        self._refresh_all()

    def _shift_date(self, delta: int):
        try:
            dt = datetime.strptime(self.date_var.get().strip(), "%Y-%m-%d")
        except ValueError:
            dt = datetime.today()
        self.date_var.set((dt + timedelta(days=delta)).strftime("%Y-%m-%d"))

    def _pick_calendar_date(self, date_str: str):
        self.date_var.set(date_str)
        self.status_var.set(f"已選取日期 {date_str}，可直接在右側輸入金額並按 OK 記帳。")
        self._render_calendar()

    def _eval_amount_expr(self, expr: str) -> float:
        cleaned = expr.replace(",", "").replace(" ", "").rstrip("+-")
        if not cleaned:
            raise ValueError("金額不可為空")
        if not re.fullmatch(r"[0-9+\-.]+", cleaned):
            raise ValueError("包含無效字元")
        tokens = re.findall(r"[+-]?(?:\d+\.?\d*|\.\d+)", cleaned)
        if "".join(tokens) != cleaned:
            raise ValueError("算式格式錯誤")
        return sum(float(tok) for tok in tokens)

    def _on_keypad(self, key: str):
        cur = self.amount_var.get().strip()
        if key == "C":
            self.amount_var.set("")
        elif key == "⌫":
            self.amount_var.set(cur[:-1])
        elif key in ("+50", "+100"):
            add_val = int(key[1:])
            try:
                base = self._eval_amount_expr(cur) if cur else 0.0
            except ValueError:
                base = 0.0
            total = base + add_val
            self.amount_var.set(str(int(total)) if total.is_integer() else f"{total:.2f}")
        elif key == "=":
            try:
                val = self._eval_amount_expr(cur)
                self.amount_var.set(str(int(val)) if val.is_integer() else f"{val:.2f}")
            except ValueError:
                messagebox.showerror("算式錯誤", "請確認輸入的數字或加減算式。")
        elif key in ("+", "-"):
            if cur and cur[-1] not in ("+", "-"):
                self.amount_var.set(cur + key)
        elif key == ".":
            last_num = re.split(r"[+-]", cur)[-1]
            if "." not in last_num:
                self.amount_var.set((cur if cur else "0") + ".")
        else:
            self.amount_var.set(cur + key)

    # ==========================================
    # 資料操作 & 行內預算調整
    # ==========================================
    def handle_add_transaction(self):
        date = self.date_var.get().strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            messagebox.showerror("日期錯誤", "請輸入 YYYY-MM-DD 格式日期（例如 2026-11-20）。")
            return

        try:
            amount = self._eval_amount_expr(self.amount_var.get())
            if amount <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("金額錯誤", "請輸入大於 0 的有效數字或算式。")
            return

        cat_name = self.category_var.get().strip() or "其他"
        category = self.account.get_or_create_category(cat_name)
        trans_type = self.trans_type_var.get()
        note = self.note_var.get().strip()

        t = Transaction(date, trans_type, category, amount, note)
        warning = self.account.add_transaction(t)

        if not self.show_all_months:
            self.current_month = t.get_month()

        self.amount_var.set("")
        self.note_var.set("")
        self._render_tag_chips(category.name)
        self._refresh_all()

        if warning:
            self.status_var.set(f"⚠️ 【預算超支警告】{warning}")
            messagebox.showwarning("預算超支警告", warning)
        else:
            self.status_var.set(f"已記帳：{date} {trans_type}「{category.icon} {category.name}」${amount:,.0f}")

    def handle_delete_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("提示", "請先在明細列表中點選一筆要刪除的紀錄。")
            return
        idx = int(selected[0])
        active_filter = "全部" if self.show_all_months else self.current_month
        rows = self.account.get_filtered_transactions(active_filter, self.search_var.get())
        if 0 <= idx < len(rows):
            target = rows[idx]
            self.account.delete_transaction(target)
            self._refresh_all()
            self.status_var.set(f"已刪除：[{target.date}] {target.category.name} ${target.amount:,.0f}")

    def handle_load_sample(self):
        self.account.load_sample_data()
        self.show_all_months = False
        self.current_month = datetime.today().strftime("%Y-%m")
        self._refresh_all()
        self.status_var.set("已載入範例資料！可切換「📅 月曆」、「📊 報表」與「🎯 預算」查看效果。")

    def handle_export_csv(self):
        if not self.account.transactions:
            messagebox.showinfo("提示", "目前沒有任何紀錄可匯出。")
            return
        filepath = filedialog.asksaveasfilename(
            title="匯出 CSV 檔",
            defaultextension=".csv",
            initialfile=f"budget_{self.current_month}.csv",
            filetypes=[("CSV 檔案", "*.csv")],
        )
        if not filepath:
            return
        try:
            self.account.export_to_csv(filepath)
            self.status_var.set(f"匯出成功：{filepath}")
            messagebox.showinfo("匯出成功", f"已成功匯出至：\n{filepath}")
        except OSError as e:
            messagebox.showerror("匯出失敗", str(e))

    def _toggle_inline_budget_editor(self, cat_name: str):
        if self.editing_budget_cat == cat_name:
            self.editing_budget_cat = None
        else:
            self.editing_budget_cat = cat_name
        active_filter = "全部" if self.show_all_months else self.current_month
        self._render_budget_cards(self.account.get_category_expenses(active_filter))

    def _nudge_inline_budget(self, delta: int):
        if self._inline_budget_var is None:
            return
        try:
            cur = float(self._inline_budget_var.get().strip() or 0)
        except ValueError:
            cur = 0.0
        new_val = max(0.0, cur + delta)
        self._inline_budget_var.set(str(int(new_val)) if new_val.is_integer() else f"{new_val:.0f}")

    def _save_inline_budget(self, cat_name: str):
        if self._inline_budget_var is None:
            return
        try:
            val = float(self._inline_budget_var.get().strip())
            if val < 0:
                raise ValueError
        except ValueError:
            self.status_var.set("預算格式錯誤：請輸入大於等於 0 的數字（0 代表不設上限）。")
            return
        self.account.set_category_budget(cat_name, val)
        self.editing_budget_cat = None
        self._refresh_all()
        self.status_var.set(f"已將「{cat_name}」每月預算更新為 ${val:,.0f}。")

    # ==========================================
    # 畫面更新與各分頁渲染
    # ==========================================
    def _refresh_all(self):
        active_filter = "全部" if self.show_all_months else self.current_month
        self.month_lbl.configure(text="全部月份" if self.show_all_months else self.current_month)
        self.all_month_btn.configure(
            text="回當月" if self.show_all_months else "全部月份",
            bg=self.BLUE if self.show_all_months else "#FFFFFF",
        )

        income, expense, balance = self.account.get_summary(active_filter)
        self._last_inc, self._last_exp = income, expense

        self.expense_lbl.configure(text=f"${expense:,.0f}")
        self.income_lbl.configure(text=f"${income:,.0f}")
        self.balance_lbl.configure(text=f"${balance:,.0f}")

        if balance < 0:
            self.bal_box.configure(bg=self.RED_SOFT)
            self.bal_title_lbl.configure(bg=self.RED_SOFT, fg=self.RED_TEXT)
            self.balance_lbl.configure(bg=self.RED_SOFT, fg=self.RED_TEXT)
            self.ratio_hint_lbl.configure(text="⚠️ 支出大於收入", bg=self.RED_SOFT, fg=self.RED_TEXT)
        else:
            self.bal_box.configure(bg="#FFFFFF")
            self.bal_title_lbl.configure(bg="#FFFFFF", fg=self.SUBTEXT)
            self.balance_lbl.configure(bg="#FFFFFF", fg=self.INK)
            self.ratio_hint_lbl.configure(text="米黃＝支出 ｜ 霧藍＝收入", bg=self.NEUTRAL, fg=self.SUBTEXT)

        self._draw_ratio_bar()
        self._refresh_records_table()
        self._render_calendar()
        cat_expenses = self.account.get_category_expenses(active_filter)
        self._draw_donut_and_legend(cat_expenses)
        self._render_budget_cards(cat_expenses)

    def _draw_ratio_bar(self):
        c = self.ratio_canvas
        c.delete("all")
        w = max(c.winfo_width(), 10)
        total = self._last_inc + self._last_exp
        if total <= 0:
            c.create_text(w // 2, 7, text="尚無收支紀錄", font=self.f_xs, fill=self.SUBTEXT)
            return
        exp_w = int((self._last_exp / total) * w)
        exp_color = self.RED if self._last_exp > self._last_inc else self.YELLOW
        if exp_w > 0:
            c.create_rectangle(0, 0, exp_w, 14, fill=exp_color, outline="")
        if exp_w < w:
            c.create_rectangle(exp_w, 0, w, 14, fill=self.BLUE, outline="")
        if 0 < exp_w < w:
            c.create_line(exp_w, 0, exp_w, 14, fill=self.BORDER, width=1)

    def _refresh_records_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        active_filter = "全部" if self.show_all_months else self.current_month
        rows = self.account.get_filtered_transactions(active_filter, self.search_var.get())
        self.record_count_lbl.configure(text=f"共 {len(rows)} 筆")
        for idx, t in enumerate(rows):
            sign = "-" if t.trans_type == "支出" else "+"
            tag = "expense" if t.trans_type == "支出" else "income"
            self.tree.insert(
                "", "end", iid=str(idx),
                values=(t.date, t.trans_type, f"{t.category.icon} {t.category.name}", t.note or "—", f"{sign}${t.amount:,.0f}"),
                tags=(tag,),
            )

    def _render_calendar(self):
        for w in self.cal_grid_frame.winfo_children():
            w.destroy()

        # 重置列權重避免跨月從 6 週切回 5 週時殘留空列
        for r in range(1, 7):
            self.cal_grid_frame.rowconfigure(r, weight=0, uniform="")

        y, m = map(int, self.current_month.split("-"))
        self.cal_title_lbl.configure(text=f"{y} 年 {m} 月收支月曆（點選日期切換右側記帳日）")

        daily = self.account.get_daily_totals(self.current_month)
        selected_date = self.date_var.get().strip()

        for col in range(7):
            self.cal_grid_frame.columnconfigure(col, weight=1, uniform="day")

        weekdays = ["日", "一", "二", "三", "四", "五", "六"]
        for col, wd in enumerate(weekdays):
            bg_c = self.RED_SOFT if col in (0, 6) else self.NEUTRAL
            tk.Label(
                self.cal_grid_frame, text=wd, font=self.f_cal_head, bg=bg_c, fg=self.INK,
                bd=1, relief="solid", pady=5,
            ).grid(row=0, column=col, sticky="ew", padx=2, pady=(0, 4))

        cal = calendar.Calendar(firstweekday=6)
        weeks = cal.monthdayscalendar(y, m)
        for r_idx, week in enumerate(weeks, start=1):
            self.cal_grid_frame.rowconfigure(r_idx, weight=1, uniform="wk")
            for c_idx, day in enumerate(week):
                if day == 0:
                    tk.Frame(
                        self.cal_grid_frame,
                        bg="#F8F8F6",
                        highlightbackground="#DCDCD6",
                        highlightthickness=1,
                        bd=0,
                    ).grid(row=r_idx, column=c_idx, sticky="nsew", padx=2, pady=2)
                    continue

                date_str = f"{y:04d}-{m:02d}-{day:02d}"
                inc, exp = daily.get(day, (0.0, 0.0))
                is_sel = (date_str == selected_date)

                if is_sel:
                    cell_bg = self.YELLOW
                elif exp > 0:
                    cell_bg = self.YELLOW_SOFT
                elif inc > 0:
                    cell_bg = self.BLUE_SOFT
                else:
                    cell_bg = "#FFFFFF"

                cell = tk.Frame(
                    self.cal_grid_frame,
                    bg=cell_bg,
                    highlightbackground=self.INK if is_sel else self.BORDER,
                    highlightthickness=2 if is_sel else 1,
                    bd=0,
                    cursor="hand2",
                )
                cell.grid(row=r_idx, column=c_idx, sticky="nsew", padx=2, pady=2)

                box = tk.Frame(cell, bg=cell_bg, cursor="hand2")
                box.pack(expand=True, fill="x", padx=2, pady=2)

                click_widgets = [cell, box]

                day_lbl = tk.Label(
                    box, text=str(day), font=self.f_cal_day, bg=cell_bg, fg=self.INK, cursor="hand2"
                )
                day_lbl.pack()
                click_widgets.append(day_lbl)

                amt_font = self.f_cal_amt_sm if (exp > 0 and inc > 0) else self.f_cal_amt
                if exp > 0:
                    exp_lbl = tk.Label(
                        box, text=f"-{exp:,.0f}", font=amt_font, bg=cell_bg, fg=self.CAL_EXP_TEXT, cursor="hand2"
                    )
                    exp_lbl.pack()
                    click_widgets.append(exp_lbl)
                if inc > 0:
                    inc_lbl = tk.Label(
                        box, text=f"+{inc:,.0f}", font=amt_font, bg=cell_bg, fg=self.CAL_INC_TEXT, cursor="hand2"
                    )
                    inc_lbl.pack()
                    click_widgets.append(inc_lbl)

                for w in click_widgets:
                    w.bind("<Button-1>", lambda _e, ds=date_str: self._pick_calendar_date(ds))

    def _draw_donut_and_legend(self, cat_expenses: dict[str, float]):
        c = self.donut_canvas
        c.delete("all")
        for w in self.chart_legend_frame.winfo_children():
            w.destroy()

        total = sum(cat_expenses.values())
        self._donut_total = total
        self._donut_hit_slices = []
        cx = cy = self.DONUT_SIZE / 2.0

        if total <= 0:
            self._donut_photo = render_smooth_donut_photo(
                self.DONUT_SIZE, self.DONUT_R_OUT, self.DONUT_R_IN, [(0.0, 360.0, self.NEUTRAL)]
            )
            c.create_image(0, 0, anchor="nw", image=self._donut_photo)
            c.create_text(cx, cy, text="尚無支出", font=self.f_md_b, fill=self.SUBTEXT)
            self._donut_text_ids = None
            tk.Label(
                self.chart_legend_frame,
                text="新增支出或點上方「✨ 範例資料」，\n即可查看清晰甜甜圈圓餅圖與佔比排行。",
                font=self.f_md,
                bg="#FFFFFF",
                fg=self.SUBTEXT,
                justify="left",
            ).pack(anchor="w", pady=20)
            return

        sorted_items = sorted(cat_expenses.items(), key=lambda x: x[1], reverse=True)
        render_slices: list[tuple[float, float, str]] = []
        cur_deg = 0.0

        for idx, (name, amt) in enumerate(sorted_items):
            cat = self.account.get_or_create_category(name)
            pct = amt / total
            next_deg = 360.0 if idx == len(sorted_items) - 1 else cur_deg + pct * 360.0
            render_slices.append((cur_deg, next_deg, cat.color))
            self._donut_hit_slices.append((cur_deg, next_deg, cat.icon, name, amt, pct * 100))
            cur_deg = next_deg

        self._donut_photo = render_smooth_donut_photo(
            self.DONUT_SIZE, self.DONUT_R_OUT, self.DONUT_R_IN, render_slices
        )
        c.create_image(0, 0, anchor="nw", image=self._donut_photo)

        t_top = c.create_text(cx, cy - 18, text="總支出", font=self.f_sm, fill=self.SUBTEXT)
        t_mid = c.create_text(cx, cy + 4, text=f"${total:,.0f}", font=("Microsoft JhengHei UI", 14, "bold"), fill=self.INK)
        t_bot = c.create_text(cx, cy + 24, text="100%", font=self.f_xs, fill=self.SUBTEXT)
        self._donut_text_ids = (t_top, t_mid, t_bot)

        tk.Label(self.chart_legend_frame, text="支出分類佔比排行", font=self.f_md_b,
                 bg="#FFFFFF", fg=self.INK).pack(anchor="w", pady=(0, 6))

        for name, amt in sorted_items:
            cat = self.account.get_or_create_category(name)
            pct = amt / total
            row = tk.Frame(self.chart_legend_frame, bg="#FFFFFF")
            row.pack(fill="x", pady=4)

            top_r = tk.Frame(row, bg="#FFFFFF")
            top_r.pack(fill="x")

            dot = tk.Canvas(top_r, width=10, height=10, bg="#FFFFFF", highlightthickness=0)
            dot.pack(side="left", padx=(0, 5), pady=2)
            dot.create_oval(1, 1, 9, 9, fill=cat.color, outline="")

            tk.Label(top_r, text=f"{cat.icon} {name}", font=self.f_sm_b, bg="#FFFFFF", fg=self.INK).pack(side="left")
            tk.Label(top_r, text=f"${amt:,.0f} ({pct * 100:.1f}%)", font=self.f_sm, bg="#FFFFFF", fg=self.SUBTEXT).pack(side="right")

            track = self._card_box(row, bg=self.NEUTRAL)
            track.configure(height=9)
            track.pack(fill="x", pady=(2, 0))
            track.pack_propagate(False)
            tk.Frame(track, bg=cat.color).place(relx=0, rely=0, relwidth=max(pct, 0.02), relheight=1)

    def _on_donut_hover(self, event):
        if not self._donut_hit_slices or not self._donut_text_ids:
            return
        cx = cy = self.DONUT_SIZE / 2.0
        dx = event.x - cx
        dy = event.y - cy
        dist = math.hypot(dx, dy)

        if self.DONUT_R_IN <= dist <= self.DONUT_R_OUT:
            angle = math.degrees(math.atan2(dx, -dy)) % 360.0
            for a0, a1, icon, name, amt, pct in self._donut_hit_slices:
                if a0 <= angle < a1 or (a1 == 360.0 and angle == 0.0):
                    t_top, t_mid, t_bot = self._donut_text_ids
                    self.donut_canvas.itemconfigure(t_top, text=f"{icon} {name}", fill=self.INK)
                    self.donut_canvas.itemconfigure(t_mid, text=f"${amt:,.0f}")
                    self.donut_canvas.itemconfigure(t_bot, text=f"{pct:.1f}%")
                    return
        self._on_donut_leave()

    def _on_donut_leave(self, _event=None):
        if not self._donut_text_ids:
            return
        t_top, t_mid, t_bot = self._donut_text_ids
        self.donut_canvas.itemconfigure(t_top, text="總支出", fill=self.SUBTEXT)
        self.donut_canvas.itemconfigure(t_mid, text=f"${self._donut_total:,.0f}")
        self.donut_canvas.itemconfigure(t_bot, text="100%")

    def _render_budget_cards(self, cat_expenses: dict[str, float]):
        for w in self.budget_list_frame.winfo_children():
            w.destroy()

        for name, cat in self.account.categories.items():
            if name == "薪資":
                continue
            spent = cat_expenses.get(name, 0.0)
            budget = cat.monthly_budget
            is_over = budget > 0 and spent > budget
            is_editing = (self.editing_budget_cat == name)

            card_bg = self.RED_SOFT if is_over else self.BG_PAPER
            card = self._card_box(self.budget_list_frame, bg=card_bg)
            card.pack(fill="x", pady=4, padx=(0, 6))

            inner = tk.Frame(card, bg=card_bg, padx=10, pady=7)
            inner.pack(fill="x")

            top = tk.Frame(inner, bg=card_bg)
            top.pack(fill="x")
            tk.Label(top, text=f"{cat.icon} {name}", font=self.f_sm_b,
                     bg=card_bg, fg=self.RED_TEXT if is_over else self.INK).pack(side="left")

            tk.Button(
                top,
                text="收合" if is_editing else "調整",
                font=self.f_xs,
                bg=self.YELLOW if is_editing else "#FFFFFF",
                fg=self.INK,
                bd=1,
                relief="solid",
                cursor="hand2",
                padx=8,
                command=lambda n=name: self._toggle_inline_budget_editor(n),
            ).pack(side="right")

            if budget > 0:
                remain = budget - spent
                info = (
                    f"⚠️ 超支 ${abs(remain):,.0f}（${spent:,.0f} / ${budget:,.0f}）"
                    if is_over else
                    f"剩餘 ${remain:,.0f}（${spent:,.0f} / ${budget:,.0f}）"
                )
            else:
                info = f"已花費 ${spent:,.0f}（未設上限）"

            tk.Label(top, text=info, font=self.f_sm, bg=card_bg,
                     fg=self.RED_TEXT if is_over else self.SUBTEXT).pack(side="right", padx=(0, 8))

            if budget > 0:
                ratio = min(spent / budget, 1.0)
                track = self._card_box(inner, bg="#FFFFFF")
                track.configure(height=9)
                track.pack(fill="x", pady=(6, 0))
                track.pack_propagate(False)
                if ratio > 0:
                    tk.Frame(track, bg=self.RED if is_over else cat.color).place(
                        relx=0, rely=0, relwidth=ratio, relheight=1
                    )

            if is_editing:
                edit_row = tk.Frame(inner, bg="#FFFFFF", bd=1, relief="solid", padx=8, pady=6)
                edit_row.pack(fill="x", pady=(8, 0))

                tk.Label(edit_row, text="每月上限 $", font=self.f_xs, bg="#FFFFFF", fg=self.SUBTEXT).pack(side="left")
                self._inline_budget_var = tk.StringVar(value=str(int(budget)))
                entry = tk.Entry(edit_row, textvariable=self._inline_budget_var, font=self.f_sm_b,
                                 width=9, bd=1, relief="solid", justify="right")
                entry.pack(side="left", padx=(2, 6), ipady=1)
                entry.focus_set()
                entry.bind("<Return>", lambda _e, n=name: self._save_inline_budget(n))

                for label, delta in (("-500", -500), ("+500", 500), ("+1000", 1000)):
                    tk.Button(
                        edit_row, text=label, font=self.f_xs, bg=self.NEUTRAL, fg=self.INK,
                        bd=1, relief="solid", cursor="hand2", padx=5,
                        command=lambda d=delta: self._nudge_inline_budget(d),
                    ).pack(side="left", padx=2)

                tk.Button(
                    edit_row, text="取消", font=self.f_xs, bg="#FFFFFF", fg=self.SUBTEXT,
                    bd=1, relief="solid", cursor="hand2", padx=6,
                    command=lambda n=name: self._toggle_inline_budget_editor(n),
                ).pack(side="right", padx=(4, 0))

                tk.Button(
                    edit_row, text="儲存", font=self.f_xs, bg=self.GREEN, fg=self.INK,
                    bd=1, relief="solid", cursor="hand2", padx=8,
                    command=lambda n=name: self._save_inline_budget(n),
                ).pack(side="right")

        self.budget_list_frame.update_idletasks()
        self.budget_canvas.configure(scrollregion=self.budget_canvas.bbox("all"))


if __name__ == "__main__":
    root = tk.Tk()
    app = SimpleAccountingApp(root)
    root.mainloop()