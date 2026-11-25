import base64
import calendar
import csv
import ctypes
import json
import math
import os
import re
import tempfile
import struct
import zlib
from collections import defaultdict
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, font as tkfont


# 自動存檔路徑（與本支 .py 檔位於同一個資料夾）
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "budget_data.json")


def _load_private_fonts() -> None:
    """載入同資料夾或 AppData\\ShimokitaBudget 內的 fonts 字型檔（僅供本程式使用）。"""
    if os.name != "nt":
        return
    try:
        gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        add_font = gdi.AddFontResourceExW
        add_font.argtypes = (ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p)
        add_font.restype = ctypes.c_int
    except Exception:
        return
    base_dir = os.path.dirname(os.path.abspath(__file__))
    local_app = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    for font_dir in (
        os.path.join(base_dir, "fonts"),
        os.path.join(local_app, "ShimokitaBudget", "fonts"),
    ):
        if not os.path.isdir(font_dir):
            continue
        try:
            entries = sorted(os.listdir(font_dir))
        except OSError:
            continue
        for name in entries:
            if name.lower().endswith((".ttf", ".otf", ".ttc")):
                try:
                    add_font(os.path.join(font_dir, name), 0x10, None)
                except Exception:
                    pass


_load_private_fonts()


# ==========================================
# 數值與日期工具
# ==========================================
def is_valid_iso_date(date_str: str) -> bool:
    """驗證是否為真實存在的 YYYY-MM-DD 日期（排除如 2026-02-31）"""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        return False
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def normalize_number(val: int | float) -> int | float:
    """若為整數則轉回 int，保留舊帳本小數的精確值不強行四捨五入"""
    f = float(val)
    if f.is_integer():
        return int(f)
    return round(f, 6)


def fmt_num(val: int | float) -> str:
    """格式化金額：整數不帶小數點，既有小數完整保留（不顯示成 $0）"""
    f = float(val)
    if abs(f) < 1e-9:
        return "0"
    if f.is_integer():
        return f"{int(f):,}"
    text = f"{f:,.6f}".rstrip("0").rstrip(".")
    return text


def fmt_currency(val: int | float) -> str:
    if val < 0:
        return f"-${fmt_num(abs(val))}"
    return f"${fmt_num(val)}"


# ==========================================
# 自製極簡現代捲動條（取代復古 ttk.Scrollbar）
# ==========================================
class ModernScrollbar(tk.Canvas):
    """無箭頭、無粗糙框線的細長圓角膠囊捲動條"""
    def __init__(
        self,
        parent,
        command=None,
        bg: str = "#FFFFFF",
        thumb_color: str = "#D8D5CC",
        hover_color: str = "#B9B5AA",
        width: int = 10,
    ):
        super().__init__(parent, width=width, bg=bg, highlightthickness=0, bd=0)
        self._command = command
        self._thumb_color = thumb_color
        self._hover_color = hover_color
        self._first = 0.0
        self._last = 1.0
        self._thumb_y0 = 0.0
        self._thumb_y1 = 0.0
        self._visible = False
        self._hovered = False
        self._dragging = False
        self._drag_start_y = 0
        self._drag_start_first = 0.0
        self._last_draw_key = None

        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

    def set(self, first, last):
        self._first = max(0.0, min(1.0, float(first)))
        self._last = max(0.0, min(1.0, float(last)))
        self._redraw()

    def _redraw(self):
        h = self.winfo_height()
        w = self.winfo_width()
        draw_key = (w, h, round(self._first, 4), round(self._last, 4), self._hovered, self._dragging)
        if draw_key == self._last_draw_key:
            return
        self._last_draw_key = draw_key
        self.delete("all")
        span = self._last - self._first
        if h <= 16 or span >= 0.999 or span <= 0.0:
            self._visible = False
            self.configure(cursor="")
            return

        self._visible = True
        self.configure(cursor="hand2")
        pad = 3
        usable = max(1.0, h - 2 * pad)
        th = max(32.0, span * usable)
        max_travel = max(1.0, usable - th)
        pos_ratio = self._first / max(1e-6, 1.0 - span)
        y0 = pad + pos_ratio * max_travel
        y1 = y0 + th
        self._thumb_y0, self._thumb_y1 = y0, y1

        x0 = 2
        x1 = max(x0 + 4, w - 2)
        d = x1 - x0
        r = d / 2.0
        color = self._hover_color if (self._hovered or self._dragging) else self._thumb_color

        self.create_oval(x0, y0, x1, y0 + d, fill=color, outline="")
        self.create_oval(x0, y1 - d, x1, y1, fill=color, outline="")
        self.create_rectangle(x0, y0 + r, x1, y1 - r, fill=color, outline="")

    def _on_enter(self, _event):
        self._hovered = True
        self._redraw()

    def _on_leave(self, _event):
        self._hovered = False
        self._redraw()

    def _on_press(self, event):
        if not self._visible or not self._command:
            return
        if self._thumb_y0 <= event.y <= self._thumb_y1:
            self._dragging = True
            self._drag_start_y = event.y
            self._drag_start_first = self._first
            self._redraw()
        else:
            h = self.winfo_height()
            pad = 3
            span = self._last - self._first
            usable = max(1.0, h - 2 * pad)
            th = max(32.0, span * usable)
            max_travel = max(1.0, usable - th)
            target_ratio = max(0.0, min(1.0, (event.y - th / 2.0 - pad) / max_travel))
            new_first = target_ratio * (1.0 - span)
            self._command("moveto", str(new_first))
            self._dragging = True
            self._drag_start_y = event.y
            self._drag_start_first = new_first

    def _on_drag(self, event):
        if not self._dragging or not self._visible or not self._command:
            return
        h = self.winfo_height()
        pad = 3
        span = self._last - self._first
        usable = max(1.0, h - 2 * pad)
        th = max(32.0, span * usable)
        max_travel = max(1.0, usable - th)
        delta_ratio = (event.y - self._drag_start_y) / max_travel
        new_first = self._drag_start_first + delta_ratio * (1.0 - span)
        new_first = max(0.0, min(1.0 - span, new_first))
        self._command("moveto", str(new_first))

    def _on_release(self, _event):
        self._dragging = False
        self._redraw()


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
    gap_half: float = 1.0,
    highlight_idx: int | None = None,
) -> tk.PhotoImage:
    """使用距離場抗鋸齒繪製平滑圓環圖（選取區塊向外微幅膨脹填滿突顯），回傳 Tkinter PhotoImage"""
    cx = cy = size / 2.0
    bg_r, bg_g, bg_b = _hex_to_rgb(bg_hex)
    bg_row = bytes((bg_r, bg_g, bg_b)) * size

    raw_slices = [(a0, a1, _hex_to_rgb(col)) for a0, a1, col in slices]
    has_gaps = len(raw_slices) > 1
    hl_active = highlight_idx is not None and 0 <= highlight_idx < len(raw_slices)

    if hl_active:
        rgb_slices = []
        for idx, (a0, a1, (sr, sg, sb)) in enumerate(raw_slices):
            if idx == highlight_idx:
                rgb_slices.append((a0, a1, (sr, sg, sb)))
            else:
                # 非選取區塊稍微柔淡 22%，讓選中扇形一體膨脹更醒目
                rgb_slices.append((
                    a0,
                    a1,
                    (
                        int(sr * 0.78 + bg_r * 0.22 + 0.5),
                        int(sg * 0.78 + bg_g * 0.22 + 0.5),
                        int(sb * 0.78 + bg_b * 0.22 + 0.5),
                    ),
                ))
    else:
        rgb_slices = raw_slices

    r_out_hl = r_out + 9.5
    r_in_hl = max(0.0, r_in - 2.5)
    max_bound = (r_out_hl if hl_active else r_out) + 1.0
    max_bound2 = max_bound * max_bound
    min_bound = max(0.0, (r_in_hl if hl_active else r_in) - 1.0)
    min_bound2 = min_bound * min_bound

    rows: list[bytearray] = []

    for y in range(size):
        dy = y + 0.5 - cy
        dy2 = dy * dy
        row = bytearray(bg_row)

        if dy2 < max_bound2 and rgb_slices:
            max_dx = math.sqrt(max_bound2 - dy2)
            x_start = max(0, int(cx - max_dx))
            x_end = min(size, int(cx + max_dx) + 1)

            for x in range(x_start, x_end):
                dx = x + 0.5 - cx
                d2 = dx * dx + dy2
                if d2 < min_bound2 or d2 > max_bound2:
                    continue

                if has_gaps:
                    angle = math.degrees(math.atan2(dx, -dy)) % 360.0
                    s_idx = len(rgb_slices) - 1
                    s_deg, e_deg, (sr, sg, sb) = rgb_slices[-1]
                    for i, (a0, a1, rgb) in enumerate(rgb_slices):
                        if a0 <= angle < a1:
                            s_idx = i
                            s_deg, e_deg = a0, a1
                            sr, sg, sb = rgb
                            break
                else:
                    s_idx = 0
                    s_deg, e_deg, (sr, sg, sb) = rgb_slices[0]

                is_hl_slice = hl_active and s_idx == highlight_idx
                slice_r_out = r_out_hl if is_hl_slice else r_out
                slice_r_in = r_in_hl if is_hl_slice else r_in

                dist = math.sqrt(d2)
                c_out = slice_r_out - dist + 0.5
                if c_out <= 0.0:
                    continue
                if c_out > 1.0:
                    c_out = 1.0

                c_in = dist - slice_r_in + 0.5
                if c_in <= 0.0:
                    continue
                if c_in > 1.0:
                    c_in = 1.0

                alpha = c_out * c_in

                if has_gaps:
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
    """收支類別（含圖示、色塊與每月預算上限）"""
    def __init__(self, name: str, monthly_budget: int | float = 0, icon: str = "📌", color: str = "#A7AEB8"):
        self.name = name
        self.monthly_budget = normalize_number(monthly_budget)
        self.icon = icon
        self.color = color

    def set_monthly_budget(self, budget: int | float):
        self.monthly_budget = normalize_number(budget)


class Transaction:
    """單筆收支紀錄（新入帳為正整數，同時相容保留舊帳本小數紀錄）"""
    def __init__(self, date: str, trans_type: str, category: Category, amount: int | float, note: str = ""):
        self.date = date              # YYYY-MM-DD
        self.trans_type = trans_type  # "支出" 或 "收入"
        self.category = category
        self.amount = normalize_number(amount)
        self.note = note

    def get_month(self) -> str:
        return self.date[:7] if len(self.date) >= 7 else "未知月份"

    def get_reason(self) -> str:
        """回傳花費／收入事由（優先顯示備註，沒有則顯示分類名稱）"""
        return self.note.strip() if self.note.strip() else self.category.name

    def to_csv_row(self) -> list:
        return [self.date, self.trans_type, self.category.name, self.amount, self.note]


class Account:
    """帳戶管理、收支統計、預算警告、本地自動存檔與 CSV 匯出"""
    def __init__(self, account_name: str, data_file: str = DATA_FILE):
        self.account_name = account_name
        self.data_file = data_file
        self.is_dirty = False
        self.transactions: list[Transaction] = []
        self.categories: dict[str, Category] = {
            "飲食": Category("飲食", 6000, "🍔", "#D9A97E"),
            "飲料": Category("飲料", 1500, "🧋", "#D4A3B0"),
            "交通": Category("交通", 1500, "🚇", "#8FAEC6"),
            "娛樂": Category("娛樂", 2000, "🎮", "#AFA1C4"),
            "日用": Category("日用", 1500, "🛍", "#8FBAB0"),
            "購物": Category("購物", 2500, "🛒", "#D8C388"),
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

    def save_data(self) -> bool:
        payload = {
            "categories": {
                name: {
                    "monthly_budget": normalize_number(cat.monthly_budget),
                    "icon": cat.icon,
                    "color": cat.color,
                }
                for name, cat in self.categories.items()
            },
            "category_tags": self.category_tags,
            "transactions": [
                {
                    "date": t.date,
                    "trans_type": t.trans_type,
                    "category": t.category.name,
                    "amount": normalize_number(t.amount),
                    "note": t.note,
                }
                for t in self.transactions
            ],
        }
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False,
                                             dir=os.path.dirname(os.path.abspath(self.data_file))) as f:
                temporary = f.name
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(temporary, self.data_file)
            self.is_dirty = False
            return True
        except OSError as e:
            messagebox.showwarning(
                "存檔失敗",
                f"無法儲存資料至 {self.data_file}：\n{e}\n\n請確認檔案權限、磁碟空間或是否被其他程式鎖定。",
            )
            return False
        finally:
            if temporary and os.path.exists(temporary):
                try:
                    os.remove(temporary)
                except OSError:
                    pass

    def load_data(self) -> int:
        """唯讀載入舊帳本：完整保留既有金額（包含小數），絕不在讀取時覆寫或刪除存檔"""
        if not os.path.exists(self.data_file):
            return 0
        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            return 0

        saved_cats = payload.get("categories", {})
        if isinstance(saved_cats, dict):
            for name, info in saved_cats.items():
                try:
                    budget = max(0, normalize_number(float(info.get("monthly_budget", 0))))
                except (ValueError, TypeError):
                    budget = 0
                if name in self.categories:
                    self.categories[name].set_monthly_budget(budget)
                else:
                    self.categories[name] = Category(
                        name,
                        budget,
                        info.get("icon", "🏷"),
                        info.get("color", "#9EA8BD"),
                    )

        saved_tags = payload.get("category_tags", {})
        if isinstance(saved_tags, dict):
            for name, tags in saved_tags.items():
                if isinstance(tags, list):
                    self.category_tags[name] = [str(tag) for tag in tags]

        self.transactions.clear()
        for row in payload.get("transactions", []):
            try:
                date_str = str(row["date"]).strip()
                amt = normalize_number(float(row["amount"]))
                if amt <= 0:
                    continue
                cat = self.get_or_create_category(str(row.get("category", "其他")))
                self.transactions.append(
                    Transaction(
                        date_str,
                        str(row["trans_type"]),
                        cat,
                        amt,
                        str(row.get("note", "")),
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue

        self.transactions.sort(key=lambda x: x.date, reverse=True)
        self.is_dirty = False
        return len(self.transactions)

    def get_or_create_category(self, name: str) -> Category:
        name = name.strip() or "其他"
        if name not in self.categories:
            self.categories[name] = Category(name, 0, "🏷", "#9EA8BD")
        return self.categories[name]

    def set_category_budget(self, name: str, budget: int):
        cat = self.get_or_create_category(name)
        cat.set_monthly_budget(int(budget))
        self.is_dirty = True
        self.save_data()

    def get_tags_for_category(self, cat_name: str) -> list[str]:
        return self.category_tags.get(cat_name, [])[:6]

    def add_transaction(self, t: Transaction, auto_save: bool = True) -> str | None:
        self.transactions.append(t)
        self.transactions.sort(key=lambda x: x.date, reverse=True)

        if t.note:
            tags = self.category_tags.setdefault(t.category.name, [])
            if t.note not in tags:
                tags.insert(0, t.note)

        self.is_dirty = True
        if auto_save:
            self.save_data()

        if t.trans_type == "支出":
            return self.check_budget_warning(t.category, t.get_month())
        return None

    def delete_transaction(self, target: Transaction):
        if target in self.transactions:
            self.transactions.remove(target)
            self.is_dirty = True
            self.save_data()

    def clear_transactions(self):
        self.transactions.clear()
        self.is_dirty = True
        self.save_data()

    def check_budget_warning(self, category: Category, month: str) -> str | None:
        budget = category.monthly_budget
        if budget <= 0:
            return None
        spent = normalize_number(
            sum(
                t.amount for t in self.transactions
                if t.trans_type == "支出" and t.category.name == category.name and t.get_month() == month
            )
        )
        if spent > budget:
            over = normalize_number(spent - budget)
            return f"{month}「{category.name}」累計支出 ${fmt_num(spent)}，超出預算 ${fmt_num(over)}"
        return None

    def get_filtered_transactions(self, month: str = "全部", keyword: str = "") -> list[Transaction]:
        rows = self.transactions if (not month or month == "全部") else [t for t in self.transactions if t.get_month() == month]
        kw = keyword.strip().lower()
        if kw:
            rows = [t for t in rows if kw in t.category.name.lower() or kw in t.note.lower() or kw in t.date]
        return list(rows)

    def get_summary(self, month: str = "全部") -> tuple[int | float, int | float, int | float]:
        rows = self.get_filtered_transactions(month)
        income = normalize_number(sum(t.amount for t in rows if t.trans_type == "收入"))
        expense = normalize_number(sum(t.amount for t in rows if t.trans_type == "支出"))
        return income, expense, normalize_number(income - expense)

    def get_category_totals(self, month: str = "全部", trans_type: str = "支出") -> dict[str, int | float]:
        totals: dict[str, float] = defaultdict(float)
        for t in self.get_filtered_transactions(month):
            if t.trans_type == trans_type:
                totals[t.category.name] += t.amount
        return {k: normalize_number(v) for k, v in totals.items()}

    def get_category_expenses(self, month: str = "全部") -> dict[str, int | float]:
        return self.get_category_totals(month, "支出")

    def get_category_monthly_expenses(self) -> dict[str, dict[str, int | float]]:
        """依「分類 -> 月份」彙總各單月支出，供「全部月份」模式逐月檢查預算上限"""
        nested: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for t in self.transactions:
            if t.trans_type == "支出":
                nested[t.category.name][t.get_month()] += t.amount
        return {
            cat: {m: normalize_number(v) for m, v in months.items()}
            for cat, months in nested.items()
        }

    def get_daily_transactions(self, month: str) -> dict[int, list[Transaction]]:
        """回傳指定月份每日的完整收支明細清單（支出優先、金額大到小）"""
        daily = defaultdict(list)
        for t in self.transactions:
            if t.get_month() == month and is_valid_iso_date(t.date):
                day = int(t.date[8:10])
                daily[day].append(t)
        for day_rows in daily.values():
            day_rows.sort(key=lambda x: (0 if x.trans_type == "支出" else 1, -x.amount))
        return dict(daily)

    def get_transactions_on_date(self, date_str: str) -> list[Transaction]:
        rows = [t for t in self.transactions if t.date == date_str]
        rows.sort(key=lambda x: (0 if x.trans_type == "支出" else 1, -x.amount))
        return rows

    def export_to_csv(self, filename: str, transactions: list[Transaction] | None = None):
        rows = self.transactions if transactions is None else transactions
        with open(filename, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["日期", "類型", "類別", "金額", "備註"])
            for t in rows:
                writer.writerow(t.to_csv_row())


# ==========================================
# 主介面
# ==========================================
class SimpleAccountingApp:
    BG_PAPER = "#F4F3EF"
    CARD_BG = "#FFFFFF"
    INK = "#353940"
    SUBTEXT = "#727882"

    BORDER = "#E3E1DA"
    BORDER_INPUT = "#D6D4CC"
    BORDER_FOCUS = "#A8A49A"
    TILE_BG = "#F6F5F1"
    TILE_HOVER = "#ECEAE3"

    YELLOW = "#E6D3A3"
    YELLOW_SOFT = "#FAF6EA"
    BLUE = "#B8CEDE"
    BLUE_SOFT = "#EFF4F8"
    RED = "#D99595"
    RED_SOFT = "#F8ECEC"
    RED_TEXT = "#A84A4A"
    GREEN = "#BAD2C0"
    NEUTRAL = "#EFECE5"

    CAL_EXP_TEXT = "#9B5E2E"
    CAL_INC_TEXT = "#2F6B88"

    DONUT_SIZE = 250
    DONUT_R_OUT = 108.0
    DONUT_R_IN = 68.0

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("個人記帳與預算分析工具")
        self.root.geometry("1220x760")
        self.root.minsize(1060, 680)
        self.root.configure(bg=self.BG_PAPER)

        self.account = Account("我的個人帳本")
        loaded_count = self.account.load_data()

        installed_fonts = set(tkfont.families(self.root))

        def pick_font(candidates):
            for name in candidates:
                if name in installed_fonts:
                    return name
            return candidates[-1]

        def styled_font(face, size, bold_if_plain=True):
            if bold_if_plain and not any(k in face for k in ("Medium", "SemiBold", "Semibold", "Bold", "中黑", "中粗", "粗體")):
                return (face, size, "bold")
            return (face, size)

        ui_reg = pick_font((
            "SF Pro TC", "PingFang TC", "PingFang TC Regular", "蘋方-繁", "蘋方-繁 標準體",
            "PingFangTC-Regular", "PingFang HK",
            "Noto Sans TC", "Noto Sans CJK TC", "Source Han Sans TC",
            "Microsoft JhengHei", "Microsoft JhengHei UI",
        ))
        ui_med = pick_font((
            "SF Pro TC Medium", "PingFang TC Medium", "蘋方-繁 中黑體", "PingFangTC-Medium", "PingFang HK Medium",
            "SF Pro TC", "PingFang TC", "蘋方-繁", "PingFang HK",
            "Noto Sans TC Medium", "Noto Sans CJK TC Medium", "Source Han Sans TC Medium",
            "Noto Sans TC", "Microsoft JhengHei", "Microsoft JhengHei UI",
        ))
        num_med = pick_font((
            "SF Pro Display Medium", "SF Pro Text Medium", "SF Pro Medium",
            "SF Pro Display", "SF Pro", "SF Pro Text",
            "Inter Medium", "Inter",
            "Helvetica Neue", "Segoe UI Variable Display",
            ui_med,
        ))
        num_semi = pick_font((
            "SF Pro Display Semibold", "SF Pro Display SemiBold", "SF Pro Text Semibold", "SF Pro Semibold",
            "SF Pro Display Medium", "SF Pro Display", "SF Pro", "SF Pro Text",
            "Inter SemiBold", "Inter Medium", "Inter",
            "Helvetica Neue", "Segoe UI Variable Display",
            ui_med,
        ))
        self.ui_font_reg = ui_reg
        self.ui_font_med = ui_med
        self.num_font_med = num_med
        self.num_font_semi = num_semi
        for tk_fname in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(tk_fname).configure(family=ui_reg)
            except tk.TclError:
                pass

        self.f_xs = (ui_reg, 10)
        self.f_sm = (ui_reg, 11)
        self.f_sm_b = styled_font(ui_med, 11)
        self.f_md = (ui_reg, 12)
        self.f_md_b = styled_font(ui_med, 12)
        self.f_lg_b = styled_font(ui_med, 14)
        self.f_xl_b = styled_font(num_semi, 21)
        self.f_num_key = styled_font(num_med, 14)
        self.f_num_ok = styled_font(num_semi, 15)
        self.f_num_dollar = styled_font(num_med, 22)
        self.f_num_input = styled_font(num_semi, 24)
        self.f_donut_mid = styled_font(num_semi, 16)

        # 月曆字體物件（用於精準量測文字像素寬度，避免金額被擠掉）
        self.f_cal_head = styled_font(ui_med, 12)
        self.f_cal_day_lg = styled_font(num_med, 12)
        self.f_cal_day_sm = styled_font(num_med, 10)
        cal_amt_weight = "normal" if any(k in num_med for k in ("Medium", "SemiBold", "Semibold", "Bold", "中黑", "中粗", "粗體")) else "bold"
        self.font_cal_item_lg = tkfont.Font(family=ui_reg, size=9)
        self.font_cal_amt_lg = tkfont.Font(family=num_med, size=9, weight=cal_amt_weight)
        self.font_cal_item_sm = tkfont.Font(family=ui_reg, size=8)
        self.font_cal_amt_sm = tkfont.Font(family=num_med, size=8, weight=cal_amt_weight)

        self.current_month = datetime.today().strftime("%Y-%m")
        self.show_all_months = False
        self.active_tab = "records"
        self.editing_budget_cat: str | None = None
        self._inline_budget_var: tk.StringVar | None = None

        # 明細畫面快取，刪除時直接對照實際顯示列避免索引錯位
        self._displayed_rows: list[Transaction] = []
        self._records_focus: str = "search"  # "search" / "delete" / "table"
        self._budget_order: list[str] = []
        self._budget_card_widgets: dict[str, tuple[tk.Frame, str]] = {}
        self._budget_selected_idx: int = 0
        self._right_row: int = 1
        self._right_col: int = 0
        self._right_return_zone: str = "calendar"
        self._right_rows_top: list[list[tuple]] = []
        self._right_tag_row: list[tuple] = []
        self._right_rows_bottom: list[list[tuple]] = []
        self._amt_box_border: str = "#EAE2CD"

        # 月曆無閃爍選取快取
        self._cal_daily = {}
        self._cal_resize_job: str | None = None
        self._last_selected_cal_date: str = ""
        self._cal_rendered_month: str = ""
        self._cal_cells: dict[str, tuple[int, str]] = {}
        self._ime_disabled: bool = False
        self._win_ime = self._init_win_ime()
        self._win_class_optimized: bool = False
        self._win_bg_brush = None

        self._donut_photo: tk.PhotoImage | None = None
        self._donut_img_id: int | None = None
        self._donut_render_slices: list[tuple[float, float, str]] = []
        self._donut_photo_cache: dict[int | None, tk.PhotoImage] = {}
        self._donut_active_highlight: int | None = None
        self._donut_hit_slices: list[tuple[float, float, str, str, int | float, float, str]] = []
        self._donut_total: int | float = 0
        self._donut_text_ids: tuple[int, int, int] | None = None
        self.chart_type: str = "支出"
        self._chart_order: list[str] = []
        self._chart_legend_items: list[tuple[str, str, str, int | float, float]] = []
        self._chart_row_rects: dict[str, tuple[int, float, float]] = {}
        self._chart_legend_w: int = 0
        self._chart_legend_total_h: int = 0
        self._chart_selected_idx: int = 0
        self._chart_focus_area: str = "list"  # "toggle" / "list"

        self._last_focus_is_input: bool | None = None
        self._last_ratio_key: tuple | None = None
        self._last_budget_canvas_w: int = 0

        self._normalizing_amount = False
        self._normalizing_budget = False
        self._inline_budget_entry: tk.Entry | None = None
        self.trans_type_var = tk.StringVar(value="支出")
        self.category_var = tk.StringVar(value="飲食")
        self.date_var = tk.StringVar(value=datetime.today().strftime("%Y-%m-%d"))
        self.amount_var = tk.StringVar(value="")
        self.amount_var.trace_add("write", self._on_amount_var_changed)
        self.note_var = tk.StringVar(value="")
        self.search_var = tk.StringVar(value="")

        init_msg = f"已讀取 {loaded_count} 筆紀錄" if loaded_count > 0 else "目前尚無紀錄"
        self.status_var = tk.StringVar(value=init_msg)

        self._setup_styles()
        self._build_layout()
        self._select_type("支出")
        self._select_category("飲食")
        self._refresh_all()

        self.root.bind_all("<MouseWheel>", self._on_global_mousewheel)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Map>", self._optimize_win32_window, add="+")
        self.root.after_idle(self._optimize_win32_window)

    def _on_close(self):
        # 僅在有實際異動時才寫入檔案，避免單純檢視舊帳本時覆寫存檔
        if self.account.is_dirty and not self.account.save_data():
            return
        self.root.destroy()

    def _on_global_mousewheel(self, event):
        target_canvas = None
        target_tab = None
        if self.active_tab == "budgets":
            target_canvas = self.budget_canvas
            target_tab = self.tab_frames["budgets"]
        elif self.active_tab == "charts":
            target_canvas = self.chart_legend_canvas
            target_tab = self.tab_frames["charts"]
        if target_canvas is None:
            return
        w = event.widget
        while w is not None:
            if w == target_tab:
                first, last = target_canvas.yview()
                if not (first <= 0.0 and last >= 1.0):
                    target_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                return
            w = w.master

    def _card_box(self, parent, bg="#FFFFFF", width=None, border=None):
        b_col = border or self.BORDER
        kwargs = dict(bg=bg, highlightbackground=b_col, highlightcolor=b_col, highlightthickness=1, bd=0)
        if width is not None:
            kwargs["width"] = width
        return tk.Frame(parent, **kwargs)

    def _soft_entry(self, parent, textvariable, font, width=None, justify="left"):
        kwargs = dict(
            textvariable=textvariable,
            font=font,
            bg="#FFFFFF",
            fg=self.INK,
            bd=0,
            relief="flat",
            justify=justify,
            highlightthickness=1,
            highlightbackground=self.BORDER_INPUT,
            highlightcolor=self.BORDER_FOCUS,
        )
        if width is not None:
            kwargs["width"] = width
        return tk.Entry(parent, **kwargs)

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Soft.Treeview",
            font=self.f_md,
            rowheight=36,
            background="#FFFFFF",
            fieldbackground="#FFFFFF",
            borderwidth=0,
            relief="flat",
        )
        style.configure(
            "Soft.Treeview.Heading",
            font=self.f_sm_b,
            background=self.TILE_BG,
            foreground=self.SUBTEXT,
            borderwidth=0,
            relief="flat",
        )
        style.map("Soft.Treeview", background=[("selected", "#EDE6D4")], foreground=[("selected", self.INK)])
        style.layout("Soft.Treeview", [("Soft.Treeview.treearea", {"sticky": "nswe"})])

    def _build_layout(self):
        topbar = tk.Frame(self.root, bg=self.BG_PAPER)
        topbar.pack(fill="x", padx=18, pady=(10, 6))

        tk.Button(
            topbar, text="匯出 CSV", font=self.f_sm_b, bg=self.GREEN, fg=self.INK,
            activebackground="#A9C5B0", bd=0, relief="flat", cursor="hand2",
            padx=14, pady=5, command=self.handle_export_csv,
        ).pack(side="right")

        tk.Button(
            topbar, text="清除資料", font=self.f_sm_b, bg=self.RED_SOFT, fg=self.RED_TEXT,
            activebackground="#F0D8D8", bd=0, relief="flat", cursor="hand2",
            padx=14, pady=5, command=self.handle_clear_all_data,
        ).pack(side="right", padx=(0, 8))

        body = tk.Frame(self.root, bg=self.BG_PAPER)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 6))

        self.left_col = tk.Frame(body, bg=self.BG_PAPER)
        self.left_col.pack(side="left", fill="both", expand=True, padx=(0, 14))

        self.right_col = self._card_box(body, bg="#FFFFFF", width=440)
        self.right_col.pack(side="right", fill="y")
        self.right_col.pack_propagate(False)

        self._build_left_panel()
        self._build_right_panel()

        status_bar = tk.Frame(self.root, bg=self.BG_PAPER)
        status_bar.pack(fill="x", padx=18, pady=(0, 8))
        tk.Label(status_bar, textvariable=self.status_var, font=self.f_sm,
                 bg=self.BG_PAPER, fg=self.SUBTEXT, anchor="w").pack(fill="x")

    # ==========================================
    # 左側：總覽卡 + 四大分頁（明細/月曆/報表/預算）
    # ==========================================
    def _build_left_panel(self):
        summary = self._card_box(self.left_col, bg="#FFFFFF")
        summary.pack(fill="x", pady=(0, 10))

        inner = tk.Frame(summary, bg="#FFFFFF", padx=14, pady=12)
        inner.pack(fill="x")

        m_row = tk.Frame(inner, bg="#FFFFFF")
        m_row.pack(fill="x")

        tk.Button(m_row, text="◀", font=self.f_sm_b, bg=self.TILE_BG, fg=self.INK,
                  activebackground=self.TILE_HOVER, bd=0, relief="flat", cursor="hand2", width=3,
                  command=lambda: self._shift_month(-1)).pack(side="left")
        self.month_lbl = tk.Label(m_row, text=self.current_month, font=self.f_lg_b,
                                  bg="#FFFFFF", fg=self.INK, width=10)
        self.month_lbl.pack(side="left", padx=4)
        tk.Button(m_row, text="▶", font=self.f_sm_b, bg=self.TILE_BG, fg=self.INK,
                  activebackground=self.TILE_HOVER, bd=0, relief="flat", cursor="hand2", width=3,
                  command=lambda: self._shift_month(1)).pack(side="left")

        self.all_month_btn = tk.Button(
            m_row, text="全部月份", font=self.f_sm, bg=self.TILE_BG, fg=self.INK,
            activebackground=self.TILE_HOVER, bd=0, relief="flat", cursor="hand2",
            padx=12, pady=2, command=self._toggle_all_months,
        )
        self.all_month_btn.pack(side="left", padx=(8, 0))

        self.ratio_hint_lbl = tk.Label(m_row, text="", font=self.f_xs,
                                       bg=self.TILE_BG, fg=self.SUBTEXT, padx=10, pady=3)
        self.ratio_hint_lbl.pack(side="right")

        cards_row = tk.Frame(inner, bg="#FFFFFF")
        cards_row.pack(fill="x", pady=(10, 8))
        for i in range(3):
            cards_row.columnconfigure(i, weight=1, uniform="stat")

        exp_box = self._card_box(cards_row, bg=self.YELLOW_SOFT, border="#ECE4CE")
        exp_box.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        tk.Label(exp_box, text="支出", font=self.f_sm_b, bg=self.YELLOW_SOFT, fg=self.SUBTEXT).pack(anchor="w", padx=12, pady=(6, 0))
        self.expense_lbl = tk.Label(exp_box, text="$0", font=self.f_xl_b, bg=self.YELLOW_SOFT, fg=self.INK)
        self.expense_lbl.pack(anchor="w", padx=12, pady=(0, 6))

        inc_box = self._card_box(cards_row, bg=self.BLUE_SOFT, border="#D9E4EC")
        inc_box.grid(row=0, column=1, sticky="ew", padx=3)
        tk.Label(inc_box, text="收入", font=self.f_sm_b, bg=self.BLUE_SOFT, fg=self.SUBTEXT).pack(anchor="w", padx=12, pady=(6, 0))
        self.income_lbl = tk.Label(inc_box, text="$0", font=self.f_xl_b, bg=self.BLUE_SOFT, fg=self.INK)
        self.income_lbl.pack(anchor="w", padx=12, pady=(0, 6))

        self.bal_box = self._card_box(cards_row, bg=self.TILE_BG, border=self.BORDER)
        self.bal_box.grid(row=0, column=2, sticky="ew", padx=(6, 0))
        self.bal_title_lbl = tk.Label(self.bal_box, text="本期結餘", font=self.f_sm_b, bg=self.TILE_BG, fg=self.SUBTEXT)
        self.bal_title_lbl.pack(anchor="w", padx=12, pady=(6, 0))
        self.balance_lbl = tk.Label(self.bal_box, text="$0", font=self.f_xl_b, bg=self.TILE_BG, fg=self.INK)
        self.balance_lbl.pack(anchor="w", padx=12, pady=(0, 6))

        bar_wrap = tk.Frame(inner, bg=self.NEUTRAL)
        bar_wrap.pack(fill="x")
        self.ratio_canvas = tk.Canvas(bar_wrap, height=12, bg=self.NEUTRAL, highlightthickness=0)
        self.ratio_canvas.pack(fill="x")
        self.ratio_canvas.bind("<Configure>", lambda _e: self._draw_ratio_bar())
        self._last_inc: int | float = 0
        self._last_exp: int | float = 0

        tab_bar = self._card_box(self.left_col, bg="#ECEAE4", border=self.BORDER)
        tab_bar.pack(fill="x", pady=(0, 8))
        tab_inner = tk.Frame(tab_bar, bg="#ECEAE4", padx=4, pady=4)
        tab_inner.pack(fill="x")
        for i in range(4):
            tab_inner.columnconfigure(i, weight=1, uniform="tabs")

        self.tab_buttons = {}
        self.tab_wrappers = {}
        self.tab_order = ("records", "calendar", "charts", "budgets")
        self.tab_labels = {
            "records": "明細",
            "calendar": "月曆",
            "charts": "報表",
            "budgets": "預算",
        }
        self._nav_zone = "tabs"  # "tabs" 或 "calendar"
        self._focused_tab_idx = 0
        tab_defs = [
            ("records", "📋 明細"),
            ("calendar", "📅 月曆"),
            ("charts", "📊 報表"),
            ("budgets", "🎯 預算"),
        ]
        for idx, (key, text) in enumerate(tab_defs):
            wrap = tk.Frame(tab_inner, bg="#ECEAE4", padx=2, pady=2)
            wrap.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 4, 0))
            btn = tk.Button(
                wrap, text=text, font=self.f_md_b, bd=0, relief="flat",
                cursor="hand2", pady=5, command=lambda k=key: self._switch_tab(k),
            )
            btn.pack(fill="both", expand=True)
            self.tab_wrappers[key] = wrap
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
        self._switch_tab("records", enter_content=False)

    def _build_records_tab(self, parent: tk.Frame):
        top = tk.Frame(parent, bg="#FFFFFF", padx=12, pady=10)
        top.pack(fill="x")

        tk.Label(top, text="搜尋：", font=self.f_sm_b, bg="#FFFFFF", fg=self.INK).pack(side="left")
        self.search_wrap = tk.Frame(top, bg="#FFFFFF", padx=2, pady=2)
        self.search_wrap.pack(side="left")
        self.search_entry = self._soft_entry(self.search_wrap, self.search_var, self.f_sm, width=18)
        self.search_entry.pack(ipady=3)
        self.search_entry.bind("<Return>", self._on_search_entry_return)
        self.search_entry.bind("<Escape>", self._on_search_entry_escape)
        self.search_entry.bind("<Button-1>", lambda _e: self._mark_records_focus("search"), add="+")
        self.search_var.trace_add("write", lambda *_args: self._refresh_records_table())

        self.record_count_lbl = tk.Label(top, text="共 0 筆", font=self.f_sm, bg="#FFFFFF", fg=self.SUBTEXT)
        self.record_count_lbl.pack(side="left", padx=(10, 0))

        self.delete_btn_wrap = tk.Frame(top, bg="#FFFFFF", padx=2, pady=2)
        self.delete_btn_wrap.pack(side="right")
        self.delete_selected_btn = tk.Button(
            self.delete_btn_wrap, text="刪除選取", font=self.f_sm, bg=self.RED_SOFT, fg=self.RED_TEXT,
            activebackground="#F0D8D8", bd=0, relief="flat", cursor="hand2",
            padx=12, pady=3, command=self.handle_delete_selected,
        )
        self.delete_selected_btn.pack()

        wrap = tk.Frame(parent, bg="#FFFFFF", padx=12)
        wrap.pack(fill="both", expand=True, pady=(0, 10))

        cols = ("date", "type", "category", "note", "amount")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", style="Soft.Treeview")
        self.tree.bind("<Button-1>", lambda _e: self._mark_records_focus("table"), add="+")
        self.tree.heading("date", text="日期")
        self.tree.heading("type", text="類型")
        self.tree.heading("category", text="分類")
        self.tree.heading("note", text="備註")
        self.tree.heading("amount", text="金額")

        self.tree.column("date", width=115, anchor="center")
        self.tree.column("type", width=65, anchor="center")
        self.tree.column("category", width=110, anchor="w")
        self.tree.column("note", width=190, anchor="w")
        self.tree.column("amount", width=115, anchor="e")

        self.tree.tag_configure("expense", background=self.YELLOW_SOFT, foreground=self.INK)
        self.tree.tag_configure("income", background=self.BLUE_SOFT, foreground=self.INK)

        sb = ModernScrollbar(wrap, command=self.tree.yview, bg="#FFFFFF")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y", padx=(4, 0))

    def _build_calendar_tab(self, parent: tk.Frame):
        top = tk.Frame(parent, bg="#FFFFFF", padx=12, pady=8)
        top.pack(fill="x")
        self.cal_title_lbl = tk.Label(top, text="", font=self.f_md_b, bg="#FFFFFF", fg=self.INK)
        self.cal_title_lbl.pack(side="left")
        cal_hint_lbl = tk.Label(
            top, text="方向鍵 / WASD 移動日期（可跨月）· Enter 查看明細 · Esc 返回分頁列",
            font=self.f_xs, bg="#FFFFFF", fg=self.SUBTEXT,
        )
        cal_hint_lbl.pack(side="right")
        for w in (top, self.cal_title_lbl, cal_hint_lbl):
            w.bind("<Button-1>", lambda _e: self._focus_calendar())

        self.cal_body_wrap = tk.Frame(parent, bg="#FFFFFF")
        self.cal_body_wrap.pack(fill="both", expand=True, pady=(0, 6))

        self.cal_grid_frame = tk.Canvas(self.cal_body_wrap, bg="#FFFFFF", highlightthickness=0, width=1, height=1)
        self.cal_grid_frame.bind("<Button-1>", self._click_calendar)
        self.cal_grid_frame.bind("<Configure>", self._on_cal_resize)

        # 「全部月份」模式下的專屬提示畫面
        self.cal_notice_frame = tk.Frame(self.cal_body_wrap, bg="#FFFFFF", padx=12)
        notice_card = self._card_box(self.cal_notice_frame, bg=self.TILE_BG, border=self.BORDER)
        notice_card.pack(fill="both", expand=True, pady=4)
        notice_inner = tk.Frame(notice_card, bg=self.TILE_BG)
        notice_inner.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(
            notice_inner,
            text="月曆僅支援單月檢視",
            font=self.f_lg_b,
            bg=self.TILE_BG,
            fg=self.INK,
        ).pack(pady=(0, 6))
        tk.Label(
            notice_inner,
            text="目前為「全部月份」模式，請切回單月以瀏覽每日收支。",
            font=self.f_sm,
            bg=self.TILE_BG,
            fg=self.SUBTEXT,
        ).pack(pady=(0, 14))
        tk.Button(
            notice_inner,
            text="切換回當月月曆",
            font=self.f_sm_b,
            bg=self.BLUE,
            fg=self.INK,
            activebackground="#A5C0D4",
            bd=0,
            relief="flat",
            cursor="hand2",
            padx=16,
            pady=6,
            command=self._toggle_all_months,
        ).pack()

        self.day_panel = tk.Frame(self.cal_grid_frame, bg="white", highlightthickness=1,
                                  highlightbackground=self.BORDER_FOCUS, padx=10, pady=6)
        self._panel_date = ""
        self._panel_page = 0
        self._panel_items = []
        self._panel_focus_idx: int | None = None
        self._undo_jobs = {}
        self._undo_order = []
        self.root.bind("<Escape>", self._on_escape_key, add="+")
        self.root.bind("<Button-1>", self._dismiss_day_panel, add="+")
        self.root.bind("<KeyPress>", self._on_calendar_keypress, add="+")
        self.root.bind("<FocusIn>", self._sync_calendar_ime, add="+")

    def _init_win_ime(self):
        """初始化 Windows IMM32 API，供月曆鍵盤操控時暫停中文輸入法攔截 WASD"""
        if os.name != "nt":
            return None
        try:
            u = ctypes.WinDLL("user32")
            imm = ctypes.WinDLL("imm32")
            h = ctypes.c_void_p
            u.GetFocus.restype = h
            u.GetAncestor.restype = h
            u.GetAncestor.argtypes = (h, ctypes.c_uint)
            imm.ImmGetContext.restype = h
            imm.ImmGetContext.argtypes = (h,)
            imm.ImmReleaseContext.restype = ctypes.c_int
            imm.ImmReleaseContext.argtypes = (h, h)
            imm.ImmNotifyIME.restype = ctypes.c_int
            imm.ImmNotifyIME.argtypes = (h, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32)
            imm.ImmAssociateContextEx.restype = ctypes.c_int
            imm.ImmAssociateContextEx.argtypes = (h, h, ctypes.c_uint32)
            return (u, imm)
        except OSError:
            return None

    def _optimize_win32_window(self, event=None):
        """移除 TkTopLevel/TkChild 的 CS_HREDRAW|CS_VREDRAW 並設定底色畫刷，大幅降低縮放與從工作列還原時的閃爍與重繪延遲。"""
        if os.name != "nt" or self._win_class_optimized:
            return
        if event is not None and event.widget is not self.root:
            return
        try:
            u = ctypes.WinDLL("user32")
            g = ctypes.WinDLL("gdi32")
            h = ctypes.c_void_p
            u.GetAncestor.argtypes = (h, ctypes.c_uint)
            u.GetAncestor.restype = h
            gcl = getattr(u, "GetClassLongPtrW", u.GetClassLongW)
            scl = getattr(u, "SetClassLongPtrW", u.SetClassLongW)
            gcl.argtypes = (h, ctypes.c_int)
            gcl.restype = ctypes.c_ssize_t
            scl.argtypes = (h, ctypes.c_int, ctypes.c_ssize_t)
            scl.restype = ctypes.c_ssize_t
            g.CreateSolidBrush.argtypes = (ctypes.c_uint32,)
            g.CreateSolidBrush.restype = h

            rid = self.root.winfo_id()
            if not rid:
                return
            top = u.GetAncestor(rid, 2)  # GA_ROOT
            if self._win_bg_brush is None:
                r, gr, b = _hex_to_rgb(self.BG_PAPER)
                colorref = (b << 16) | (gr << 8) | r
                self._win_bg_brush = g.CreateSolidBrush(colorref)
            brush = self._win_bg_brush
            for hwnd in {w for w in (top, rid) if w}:
                scl(hwnd, -26, gcl(hwnd, -26) & ~0x3)  # 移除 CS_HREDRAW | CS_VREDRAW
                if brush:
                    scl(hwnd, -10, brush)  # 設定 GCL_HBRBACKGROUND 避免還原時空白閃爍
            # TkTopLevel 外框是在 <Map> 時才包在 root 外層；未完成包裹前不先鎖死完成旗標
            if top and top != rid:
                self._win_class_optimized = True
        except (OSError, tk.TclError):
            pass

    def _is_text_input_focused(self) -> bool:
        focused = self.root.focus_get()
        return isinstance(focused, (tk.Entry, ttk.Entry, tk.Text, ttk.Combobox))

    def _focus_calendar(self):
        if self.active_tab == "calendar" and not self.show_all_months:
            self._nav_zone = "calendar"
            self._focused_tab_idx = self.tab_order.index("calendar")
            self.cal_grid_frame.focus_set()
        self._update_all_nav_highlights()
        self._sync_calendar_ime(force=True)

    def _focus_records(self, part: str = "search"):
        self._nav_zone = "records"
        self._records_focus = part
        self._focused_tab_idx = self.tab_order.index("records")
        if part == "table":
            self.tree.focus_set()
            children = self.tree.get_children()
            if children and not self.tree.selection():
                self.tree.selection_set(children[0])
                self.tree.focus(children[0])
                self.tree.see(children[0])
        else:
            self.tab_frames["records"].focus_set()
        self._update_all_nav_highlights()
        self._sync_calendar_ime(force=True)
        hints = {
            "search": "明細：已選取「搜尋」（Enter 開始輸入，→/D 選刪除選取，↓/S 進清單，Esc 回分頁列）",
            "delete": "明細：已選取「刪除選取」（Enter 刪除選取列，←/A 選搜尋，↓/S 進清單，Esc 回分頁列）",
            "table": "明細清單（↑↓/WS 選列，←/A 選搜尋，→/D 選刪除選取，Esc 回分頁列）",
        }
        self.status_var.set(hints[part])

    def _mark_records_focus(self, part: str):
        self._nav_zone = "records"
        self._records_focus = part
        self._focused_tab_idx = self.tab_order.index("records")
        self._update_all_nav_highlights()

    def _on_search_entry_return(self, _event=None):
        if self._displayed_rows:
            self._focus_records("table")
        else:
            self._focus_records("search")
        return "break"

    def _on_search_entry_escape(self, _event=None):
        self._focus_records("search")
        return "break"

    def _focus_budgets(self, idx: int | None = None):
        self._nav_zone = "budgets"
        self._focused_tab_idx = self.tab_order.index("budgets")
        if self._budget_order:
            if idx is not None:
                self._budget_selected_idx = max(0, min(idx, len(self._budget_order) - 1))
            else:
                self._budget_selected_idx = max(0, min(self._budget_selected_idx, len(self._budget_order) - 1))
        self.tab_frames["budgets"].focus_set()
        self._update_all_nav_highlights()
        self._sync_calendar_ime(force=True)
        if self._budget_order:
            cat_name = self._budget_order[self._budget_selected_idx]
            self._scroll_budget_card_into_view(cat_name)
            self.status_var.set(f"預算：已選取「{cat_name}」（↑↓/WS 選擇分類，Enter 調整預算，Esc 回分頁列）")

    def _select_budget_card(self, idx: int):
        if self.editing_budget_cat is not None:
            return
        self._focus_budgets(idx)

    def _cancel_inline_budget_editor(self):
        if self.editing_budget_cat is None:
            return
        self.editing_budget_cat = None
        active_filter = "全部" if self.show_all_months else self.current_month
        self._render_budget_cards(self.account.get_category_expenses(active_filter))
        self._focus_budgets(self._budget_selected_idx)

    def _scroll_budget_card_into_view(self, cat_name: str):
        pair = self._budget_card_widgets.get(cat_name)
        if not pair:
            return
        card = pair[0]
        self.budget_list_frame.update_idletasks()
        total_h = self.budget_list_frame.winfo_height()
        view_h = self.budget_canvas.winfo_height()
        if total_h <= view_h or total_h <= 0:
            self.budget_canvas.yview_moveto(0.0)
            return
        top_y = card.winfo_y()
        bot_y = top_y + card.winfo_height()
        first, last = self.budget_canvas.yview()
        cur_top = first * total_h
        cur_bot = last * total_h
        if top_y < cur_top:
            self.budget_canvas.yview_moveto(max(0.0, top_y / total_h))
        elif bot_y > cur_bot:
            self.budget_canvas.yview_moveto(min(1.0, (bot_y - view_h) / total_h))

    def _focus_charts(self, idx: int | None = None, area: str | None = None):
        self._nav_zone = "charts"
        self._focused_tab_idx = self.tab_order.index("charts")
        if area is not None:
            self._chart_focus_area = area
        if self._chart_order:
            if idx is not None:
                self._chart_selected_idx = max(0, min(idx, len(self._chart_order) - 1))
            else:
                self._chart_selected_idx = max(0, min(self._chart_selected_idx, len(self._chart_order) - 1))
        self.tab_frames["charts"].focus_set()
        self._update_all_nav_highlights()
        self._sync_calendar_ime(force=True)
        period = "全部月份" if self.show_all_months else self.current_month
        if self._chart_focus_area == "list":
            if self._chart_order:
                cat_name = self._chart_order[self._chart_selected_idx]
                self._scroll_chart_row_into_view(cat_name)
                self.status_var.set(
                    f"報表（{period} · {self.chart_type}）：已選取「{cat_name}」（↑↓/WS 選分類，Enter 看明細，←→/AD 換月，Esc 回分頁列）"
                )
            else:
                self.status_var.set(
                    f"報表（{period} · {self.chart_type}）：尚無{self.chart_type}紀錄（←→/AD 換月，↑/W 切換支出/收入，Esc 回分頁列）"
                )
        else:
            self.status_var.set(
                f"報表（{period}）：已選取「{self.chart_type}報表」（←→/AD 切換支出/收入，↓/S 回排行與換月，Esc 回分頁列）"
            )

    def _set_chart_type(self, chart_type: str, focus_area: str | None = None):
        if chart_type not in ("支出", "收入"):
            return
        self.chart_type = chart_type
        self._chart_selected_idx = 0
        self._last_chart_key = None
        self._refresh_all()
        if self.active_tab == "charts":
            target_area = focus_area if focus_area is not None else "list"
            self._focus_charts(0, target_area)

    def _drill_down_chart_category(self, cat_name: str):
        self.search_var.set(cat_name)
        self._switch_tab("records", enter_content=False)
        if self._displayed_rows:
            self._focus_records("table")
        else:
            self._focus_records("search")
        self.status_var.set(
            f"已從報表篩選「{cat_name}」明細（↑↓/WS 選列，→/D 刪除選取，←/A 修改搜尋，Esc 回分頁列）"
        )

    def _scroll_chart_row_into_view(self, cat_name: str):
        rect_info = self._chart_row_rects.get(cat_name)
        if not rect_info:
            return
        _rect_id, top_y, bot_y = rect_info
        total_h = self._chart_legend_total_h
        view_h = self.chart_legend_canvas.winfo_height()
        if total_h <= view_h or total_h <= 0:
            self.chart_legend_canvas.yview_moveto(0.0)
            return
        first, last = self.chart_legend_canvas.yview()
        cur_top = first * total_h
        cur_bot = last * total_h
        if top_y < cur_top:
            self.chart_legend_canvas.yview_moveto(max(0.0, top_y / total_h))
        elif bot_y > cur_bot:
            self.chart_legend_canvas.yview_moveto(min(1.0, (bot_y - view_h) / total_h))

    def _enter_tab_content(self, key: str):
        if key == "calendar" and not self.show_all_months:
            self._focus_calendar()
        elif key == "records":
            self._focus_records("search")
        elif key == "budgets":
            self._focus_budgets(self._budget_selected_idx)
        elif key == "charts":
            self._focus_charts(self._chart_selected_idx, "list")
        else:
            self._enter_tab_nav(self.tab_order.index(key) if key in self.tab_order else 0)

    def _enter_tab_nav(self, idx: int | None = None):
        self._close_day_panel()
        self._nav_zone = "tabs"
        if idx is not None:
            self._focused_tab_idx = idx % len(self.tab_order)
        elif self.active_tab in self.tab_order:
            self._focused_tab_idx = self.tab_order.index(self.active_tab)
        if self.active_tab in self.tab_frames:
            self.tab_frames[self.active_tab].focus_set()
        self._update_all_nav_highlights()
        self._sync_calendar_ime(force=True)
        key = self.tab_order[self._focused_tab_idx]
        self.status_var.set(f"選取分頁：{self.tab_labels[key]}（左右 / AD 選擇，Enter 進入）")

    def _update_all_nav_highlights(self):
        self._update_tab_styles()
        self._update_records_nav_styles()
        self._update_budget_card_styles()
        self._update_chart_nav_styles()
        self._update_right_nav_styles()

    def _get_right_nav_grid(self) -> list[list[tuple]]:
        grid = list(self._right_rows_top)
        if self._right_tag_row:
            grid.append(self._right_tag_row)
        grid.extend(self._right_rows_bottom)
        return grid

    def _focus_right_panel(self, row: int | None = None, col: int | None = None, return_zone: str | None = None):
        if return_zone is not None:
            self._right_return_zone = return_zone
        self._nav_zone = "right"
        grid = self._get_right_nav_grid()
        if grid:
            if row is not None:
                self._right_row = max(0, min(row, len(grid) - 1))
            else:
                self._right_row = max(0, min(self._right_row, len(grid) - 1))
            row_items = grid[self._right_row]
            if col is not None:
                self._right_col = max(0, min(col, len(row_items) - 1))
            else:
                self._right_col = max(0, min(self._right_col, len(row_items) - 1))
        self.right_col.focus_set()
        self._update_all_nav_highlights()
        self._sync_calendar_ime(force=True)
        if grid:
            label = grid[self._right_row][self._right_col][3]
            self.status_var.set(f"右側記帳：已選取「{label}」（↑↓←→ / WASD 移動，Enter 確認，Esc 返回）")

    def _start_add_from_day_panel(self):
        self._close_day_panel()
        self._focus_right_panel(row=1, col=0, return_zone="calendar")

    def _right_selected_kind(self) -> str:
        grid = self._get_right_nav_grid()
        if not grid or self._nav_zone != "right" or self._is_text_input_focused():
            return ""
        sel_r = max(0, min(self._right_row, len(grid) - 1))
        sel_c = max(0, min(self._right_col, len(grid[sel_r]) - 1))
        return grid[sel_r][sel_c][1]

    def _update_right_nav_styles(self):
        grid = self._get_right_nav_grid()
        if not grid:
            return
        active = (self._nav_zone == "right" and not self._is_text_input_focused())
        sel_r = max(0, min(self._right_row, len(grid) - 1)) if active else -1
        sel_c = max(0, min(self._right_col, len(grid[sel_r]) - 1)) if active else -1
        for r_idx, row_items in enumerate(grid):
            for c_idx, (widget, kind, _action, _label) in enumerate(row_items):
                if kind.startswith(("cat:", "pad:")) or not widget.winfo_exists():
                    continue
                is_sel = active and r_idx == sel_r and c_idx == sel_c
                if kind == "amt_box":
                    border = "#AD8846" if is_sel else self._amt_box_border
                    widget.configure(
                        highlightbackground=border,
                        highlightcolor=border,
                        highlightthickness=2 if is_sel else 1,
                    )
                else:
                    widget.configure(bg="#AD8846" if is_sel else kind)
        self._paint_cat_canvas()
        self._paint_keypad_canvas()

    def _focus_right_entry(self, entry: tk.Entry, label: str):
        self._nav_zone = "right"
        entry.focus_set()
        entry.icursor("end")
        self._update_all_nav_highlights()
        self._sync_calendar_ime(force=True)
        self.status_var.set(f"正在輸入{label}（Enter 確認，Esc 回到右側選取）")

    def _on_right_entry_escape(self, row: int, col: int):
        self._focus_right_panel(row=row, col=col)
        return "break"

    def _on_right_entry_return(self, next_row: int, col: int = 0):
        self._focus_right_panel(row=next_row, col=col)
        return "break"

    def _update_records_nav_styles(self):
        if not hasattr(self, "search_wrap") or not hasattr(self, "delete_btn_wrap"):
            return
        active = (self.active_tab == "records" and self._nav_zone == "records" and not self._is_text_input_focused())
        self.search_wrap.configure(bg="#AD8846" if (active and self._records_focus == "search") else "#FFFFFF")
        self.delete_btn_wrap.configure(bg="#AD8846" if (active and self._records_focus == "delete") else "#FFFFFF")

    def _update_chart_nav_styles(self):
        active = (
            self.active_tab == "charts"
            and self._nav_zone == "charts"
            and not self._is_text_input_focused()
        )
        if hasattr(self, "chart_exp_wrap") and hasattr(self, "chart_inc_wrap"):
            is_exp = (self.chart_type == "支出")
            self.chart_exp_btn.configure(
                bg=self.YELLOW if is_exp else self.TILE_BG,
                fg=self.INK if is_exp else self.SUBTEXT,
            )
            self.chart_inc_btn.configure(
                bg=self.BLUE if not is_exp else self.TILE_BG,
                fg=self.INK if not is_exp else self.SUBTEXT,
            )
            toggle_focus = active and self._chart_focus_area == "toggle"
            self.chart_exp_wrap.configure(bg="#AD8846" if (toggle_focus and is_exp) else "#FFFFFF")
            self.chart_inc_wrap.configure(bg="#AD8846" if (toggle_focus and not is_exp) else "#FFFFFF")

        selected_cat = (
            self._chart_order[self._chart_selected_idx]
            if (active and self._chart_focus_area == "list" and 0 <= self._chart_selected_idx < len(self._chart_order))
            else None
        )
        hl_bg = self.YELLOW_SOFT if self.chart_type == "支出" else self.BLUE_SOFT
        for name, (rect_id, _y0, _y1) in self._chart_row_rects.items():
            is_sel = (name == selected_cat)
            self.chart_legend_canvas.itemconfigure(
                rect_id,
                fill=hl_bg if is_sel else "#FFFFFF",
                outline="#AD8846" if is_sel else "#FFFFFF",
                width=2 if is_sel else 1,
            )
        self._sync_donut_with_selection()

    def _sync_donut_with_selection(self, hover_idx: int | None = None):
        if not hasattr(self, "donut_canvas") or not self._donut_hit_slices or not self._donut_text_ids:
            return
        target_idx = hover_idx
        if target_idx is None:
            active = (
                self.active_tab == "charts"
                and self._nav_zone == "charts"
                and self._chart_focus_area == "list"
                and not self._is_text_input_focused()
            )
            if active and 0 <= self._chart_selected_idx < len(self._donut_hit_slices):
                target_idx = self._chart_selected_idx
        t_top, t_mid, t_bot = self._donut_text_ids
        if target_idx is not None and 0 <= target_idx < len(self._donut_hit_slices):
            _a0, _a1, icon, name, amt, pct, _color = self._donut_hit_slices[target_idx]
            self.donut_canvas.itemconfigure(t_top, text=f"{icon} {name}", fill=self.INK)
            self.donut_canvas.itemconfigure(t_mid, text=f"${fmt_num(amt)}")
            self.donut_canvas.itemconfigure(t_bot, text=f"{pct:.1f}%")
        else:
            target_idx = None
            self.donut_canvas.itemconfigure(t_top, text=f"總{self.chart_type}", fill=self.SUBTEXT)
            self.donut_canvas.itemconfigure(t_mid, text=f"${fmt_num(self._donut_total)}")
            self.donut_canvas.itemconfigure(t_bot, text="100%")

        if self._donut_img_id is not None and self._donut_render_slices:
            photo = self._donut_photo_cache.get(target_idx)
            if photo is None:
                photo = render_smooth_donut_photo(
                    self.DONUT_SIZE,
                    self.DONUT_R_OUT,
                    self.DONUT_R_IN,
                    self._donut_render_slices,
                    highlight_idx=target_idx,
                )
                self._donut_photo_cache[target_idx] = photo
            self._donut_photo = photo
            if self._donut_active_highlight != target_idx:
                self.donut_canvas.itemconfigure(self._donut_img_id, image=photo)
                self._donut_active_highlight = target_idx

    def _update_budget_card_styles(self):
        if not self._budget_card_widgets:
            return
        active = (
            self.active_tab == "budgets"
            and self._nav_zone == "budgets"
            and not self._is_text_input_focused()
        )
        selected_cat = (
            self._budget_order[self._budget_selected_idx]
            if (active and 0 <= self._budget_selected_idx < len(self._budget_order))
            else None
        )
        for name, (card, default_border) in self._budget_card_widgets.items():
            if not card.winfo_exists():
                continue
            if name == selected_cat:
                card.configure(highlightbackground="#AD8846", highlightcolor="#AD8846", highlightthickness=2)
            else:
                card.configure(highlightbackground=default_border, highlightcolor=default_border, highlightthickness=1)

    def _update_tab_styles(self):
        if not hasattr(self, "tab_wrappers"):
            return
        show_tab_focus = (self._nav_zone == "tabs") and not self._is_text_input_focused()
        for idx, key in enumerate(self.tab_order):
            btn = self.tab_buttons[key]
            wrap = self.tab_wrappers[key]
            is_active = (key == self.active_tab)
            is_focused = show_tab_focus and (idx == self._focused_tab_idx)
            if is_focused:
                wrap.configure(bg="#AD8846")
                btn.configure(bg=self.YELLOW_SOFT, fg=self.INK)
            elif is_active:
                wrap.configure(bg="#FFFFFF")
                btn.configure(bg="#FFFFFF", fg=self.INK)
            else:
                wrap.configure(bg="#ECEAE4")
                btn.configure(bg="#ECEAE4", fg=self.SUBTEXT)

    def _on_escape_key(self, _event=None):
        if self._panel_date:
            self._close_day_panel()
            return
        if self.editing_budget_cat is not None:
            self._cancel_inline_budget_editor()
            return
        focused = self.root.focus_get()
        if hasattr(self, "search_entry") and focused is self.search_entry:
            self._focus_records("search")
            return
        right_entries = (
            getattr(self, "amount_entry", None),
            getattr(self, "date_entry", None),
            getattr(self, "category_entry", None),
            getattr(self, "note_entry", None),
        )
        if focused in right_entries:
            self._focus_right_panel()
            return
        if self._nav_zone == "right":
            ret = self._right_return_zone
            if ret == "calendar" and self.active_tab == "calendar" and not self.show_all_months:
                self._focus_calendar()
            elif ret in ("records", "budgets", "charts") and ret == self.active_tab:
                self._enter_tab_content(ret)
            else:
                self._enter_tab_nav()
            return
        if self._is_text_input_focused():
            self._enter_tab_nav()
            return
        if self._nav_zone != "tabs":
            self._enter_tab_nav()
        else:
            self._enter_tab_content(self.active_tab)

    def _sync_calendar_ime(self, event=None, force: bool = False):
        """非輸入框操作時暫停視窗 IME（避免微軟注音攔截 WASD / 方向鍵），點入輸入框時立刻恢復"""
        is_input = self._is_text_input_focused()
        if event is not None:
            if is_input != self._last_focus_is_input:
                self._last_focus_is_input = is_input
                self._update_all_nav_highlights()
        else:
            self._last_focus_is_input = is_input
        if not self._win_ime:
            return
        focused = self.root.focus_get()
        want_disable = not is_input
        if not force and want_disable == self._ime_disabled and not (event is not None and event.widget is self.root):
            return
        u, imm = self._win_ime
        try:
            rid = self.root.winfo_id()
            if not rid:
                return
            hwnds = {rid}
            top = u.GetAncestor(rid, 2)  # GA_ROOT
            if top:
                hwnds.add(top)
            cal_id = self.cal_grid_frame.winfo_id() if hasattr(self, "cal_grid_frame") else 0
            if cal_id:
                hwnds.add(cal_id)
            cur_focus = u.GetFocus()
            if cur_focus:
                hwnds.add(cur_focus)
            if not want_disable and focused is not None:
                fid = focused.winfo_id()
                if fid:
                    hwnds.add(fid)
            for hwnd in hwnds:
                if want_disable:
                    himc = imm.ImmGetContext(hwnd)
                    if himc:
                        imm.ImmNotifyIME(himc, 0x0015, 0x0004, 0)  # NI_COMPOSITIONSTR, CPS_CANCEL
                        imm.ImmReleaseContext(hwnd, himc)
                    imm.ImmAssociateContextEx(hwnd, None, 0)
                else:
                    imm.ImmAssociateContextEx(hwnd, None, 0x0010)  # IACE_DEFAULT
            self._ime_disabled = want_disable
        except (tk.TclError, OSError):
            pass

    def _on_cal_resize(self, _event=None):
        if self.active_tab != "calendar" or self.show_all_months:
            return
        if self._cal_resize_job is None:
            self._cal_resize_job = self.root.after(16, self._paint_calendar)

    def _click_calendar(self, _event):
        self._focus_calendar()
        for tag in self.cal_grid_frame.gettags("current"):
            if tag.startswith("day_"):
                self._panel_page = 0
                self._panel_focus_idx = None
                self._panel_date = tag[4:]
                self._pick_calendar_date(tag[4:])
                return
        self._close_day_panel()

    def _move_calendar_selection(self, delta: int):
        if self.active_tab != "calendar" or self.show_all_months:
            return
        self._close_day_panel()
        raw = self.date_var.get().strip()
        if is_valid_iso_date(raw) and raw[:7] == self.current_month:
            dt = datetime.strptime(raw, "%Y-%m-%d")
            try:
                new_str = (dt + timedelta(days=delta)).date().isoformat()
            except OverflowError:
                self.status_var.set("已到可選日期的邊界")
                return
        else:
            y, m = map(int, self.current_month.split("-"))
            day = calendar.monthrange(y, m)[1] if delta < 0 else 1
            new_str = f"{y:04d}-{m:02d}-{day:02d}"
        self.date_var.set(new_str)
        self.status_var.set(f"已選取 {new_str}")
        self._sync_calendar_to_date(new_str)

    def _step_tab(self, delta: int):
        idx = self.tab_order.index(self.active_tab) if self.active_tab in self.tab_order else 0
        self._switch_tab(self.tab_order[(idx + delta) % len(self.tab_order)])

    def _resolve_tab_digit(self, event) -> int | None:
        idx = {
            "1": 0, "2": 1, "3": 2, "4": 3,
            "KP_1": 0, "KP_2": 1, "KP_3": 2, "KP_4": 3,
        }.get(event.keysym)
        if idx is None and os.name == "nt":
            idx = {
                49: 0, 50: 1, 51: 2, 52: 3,
                97: 0, 98: 1, 99: 2, 100: 3,
            }.get(event.keycode)
        return idx

    def _resolve_direction(self, event) -> str | None:
        direction = {
            "Up": "up", "w": "up", "W": "up",
            "Down": "down", "s": "down", "S": "down",
            "Left": "left", "a": "left", "A": "left",
            "Right": "right", "d": "right", "D": "right",
        }.get(event.keysym)
        if direction is None and os.name == "nt":
            direction = {
                38: "up", 87: "up",
                40: "down", 83: "down",
                37: "left", 65: "left",
                39: "right", 68: "right",
            }.get(event.keycode)
        return direction

    def _scroll_active_tab(self, step: int):
        if self.active_tab == "records":
            self.tree.yview_scroll(step, "units")
        elif self.active_tab == "charts":
            first, last = self.chart_legend_canvas.yview()
            if not (first <= 0.0 and last >= 1.0):
                self.chart_legend_canvas.yview_scroll(step, "units")
        elif self.active_tab == "budgets":
            first, last = self.budget_canvas.yview()
            if not (first <= 0.0 and last >= 1.0):
                self.budget_canvas.yview_scroll(step, "units")

    def _move_records_table_row(self, step: int):
        children = self.tree.get_children()
        if not children:
            self._focus_records("search")
            return
        sel = self.tree.selection()
        if not sel:
            idx = 0
        else:
            try:
                cur_idx = children.index(sel[0])
            except ValueError:
                cur_idx = 0
            if step < 0 and cur_idx == 0:
                self._focus_records("search")
                return
            idx = max(0, min(len(children) - 1, cur_idx + step))
        iid = children[idx]
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.tree.see(iid)
        if 0 <= idx < len(self._displayed_rows):
            t = self._displayed_rows[idx]
            self.status_var.set(f"已選取 {t.date} {t.get_reason()} ${fmt_num(t.amount)}（→/D 選刪除選取，←/A 選搜尋）")

    def _on_calendar_keypress(self, event):
        ctrl = bool(event.state & 0x0004)
        alt = bool(event.state & 0x20000)
        shift = bool(event.state & 0x0001)
        if alt:
            return

        if ctrl:
            tab_idx = self._resolve_tab_digit(event)
            if tab_idx is not None:
                self._switch_tab(self.tab_order[tab_idx], enter_content=True)
                return "break"
            if event.keysym in ("Tab", "ISO_Left_Tab"):
                self._step_tab(-1 if (shift or event.keysym == "ISO_Left_Tab") else 1)
                return "break"
            return

        focused = self.root.focus_get()
        if isinstance(focused, (tk.Entry, ttk.Entry, tk.Text, ttk.Combobox)):
            return

        direction = self._resolve_direction(event)

        # 0. 右側快速記帳面板操作模式（方向鍵 / WASD 移動，Enter 確認，Esc 返回左側）
        if self._nav_zone == "right":
            grid = self._get_right_nav_grid()
            if not grid:
                return
            self._right_row = max(0, min(self._right_row, len(grid) - 1))
            row_items = grid[self._right_row]
            self._right_col = max(0, min(self._right_col, len(row_items) - 1))
            if direction == "up":
                self._focus_right_panel(row=max(0, self._right_row - 1), col=self._right_col)
                return "break"
            if direction == "down":
                self._focus_right_panel(row=min(len(grid) - 1, self._right_row + 1), col=self._right_col)
                return "break"
            if direction == "left":
                self._focus_right_panel(row=self._right_row, col=max(0, self._right_col - 1))
                return "break"
            if direction == "right":
                self._focus_right_panel(row=self._right_row, col=min(len(row_items) - 1, self._right_col + 1))
                return "break"
            if event.keysym in ("Return", "space"):
                _, _, action, _ = row_items[self._right_col]
                action()
                return "break"
            return

        # 1. 分頁列選取模式：左右 / AD 移動選取框，按 Enter 或 ↓/S 進入分頁內容
        if self._nav_zone == "tabs":
            if direction in ("left", "right"):
                step = -1 if direction == "left" else 1
                self._enter_tab_nav(self._focused_tab_idx + step)
                return "break"
            if direction == "down":
                if self.tab_order[self._focused_tab_idx] == self.active_tab:
                    self._enter_tab_content(self.active_tab)
                    return "break"
                return "break"
            if event.keysym in ("Return", "space"):
                if not isinstance(focused, (tk.Button, ttk.Button)) or focused in self.tab_buttons.values():
                    target_key = self.tab_order[self._focused_tab_idx]
                    self._switch_tab(target_key, enter_content=True)
                    return "break"
            return

        # 2. 明細分頁操作模式：可選取「搜尋」、「刪除選取」與交易列
        if self._nav_zone == "records" and self.active_tab == "records":
            if self._records_focus in ("search", "delete"):
                if direction in ("left", "right"):
                    self._focus_records("delete" if self._records_focus == "search" else "search")
                    return "break"
                if direction == "up":
                    self._enter_tab_nav(self.tab_order.index("records"))
                    return "break"
                if direction == "down":
                    if self._displayed_rows:
                        self._focus_records("table")
                    return "break"
                if event.keysym in ("Return", "space"):
                    if self._records_focus == "search":
                        self.search_entry.focus_set()
                        self.search_entry.icursor("end")
                        self._update_all_nav_highlights()
                        self._sync_calendar_ime(force=True)
                        self.status_var.set("正在輸入搜尋關鍵字（Enter 套用進清單，Esc 結束輸入）")
                    else:
                        self.handle_delete_selected()
                    return "break"
            elif self._records_focus == "table":
                if direction == "up":
                    self._move_records_table_row(-1)
                    return "break"
                if direction == "down":
                    self._move_records_table_row(1)
                    return "break"
                if direction == "left":
                    self._focus_records("search")
                    return "break"
                if direction == "right":
                    self._focus_records("delete")
                    return "break"
                if event.keysym == "Delete":
                    self.handle_delete_selected()
                    return "break"
                if event.keysym in ("Return", "space"):
                    self._focus_records("delete")
                    return "break"
            return

        # 3. 預算分頁操作模式：上下 / WS 逐個選取分類卡，按 Enter 調整預算
        if self._nav_zone == "budgets" and self.active_tab == "budgets":
            if direction == "up":
                if not self._budget_order or self._budget_selected_idx <= 0:
                    self._enter_tab_nav(self.tab_order.index("budgets"))
                else:
                    self._focus_budgets(self._budget_selected_idx - 1)
                return "break"
            if direction == "down":
                if self._budget_order:
                    self._focus_budgets(self._budget_selected_idx + 1)
                return "break"
            if event.keysym in ("Return", "space") and not isinstance(focused, (tk.Button, ttk.Button)):
                if 0 <= self._budget_selected_idx < len(self._budget_order):
                    self._toggle_inline_budget_editor(self._budget_order[self._budget_selected_idx])
                    return "break"
            return

        # 4. 報表分頁操作模式（↑↓/WS 逐項選取與圓餅圖聯動、Enter 看分類明細、←→/AD 切換月份或支出/收入）
        if self._nav_zone == "charts" and self.active_tab == "charts":
            if self._chart_focus_area == "toggle":
                if direction == "left":
                    if self.chart_type != "支出":
                        self._set_chart_type("支出", focus_area="toggle")
                    else:
                        self._shift_month(-1)
                    return "break"
                if direction == "right":
                    if self.chart_type != "收入":
                        self._set_chart_type("收入", focus_area="toggle")
                    else:
                        self._shift_month(1)
                    return "break"
                if direction == "down":
                    self._focus_charts(self._chart_selected_idx, "list")
                    return "break"
                if direction == "up":
                    return "break"
                if event.keysym in ("Return", "space"):
                    other = "收入" if self.chart_type == "支出" else "支出"
                    self._set_chart_type(other, focus_area="toggle")
                    return "break"
                return
            if direction == "up":
                if self._chart_order and self._chart_selected_idx > 0:
                    self._focus_charts(self._chart_selected_idx - 1, "list")
                else:
                    self._focus_charts(area="toggle")
                return "break"
            if direction == "down":
                if self._chart_order:
                    self._focus_charts(min(len(self._chart_order) - 1, self._chart_selected_idx + 1), "list")
                return "break"
            if direction == "left":
                self._shift_month(-1)
                return "break"
            if direction == "right":
                self._shift_month(1)
                return "break"
            if event.keysym in ("Return", "space"):
                if 0 <= self._chart_selected_idx < len(self._chart_order):
                    self._drill_down_chart_category(self._chart_order[self._chart_selected_idx])
                    return "break"
            return

        # 5. 月曆日期操控模式（含當日明細浮窗操作）
        if self.active_tab != "calendar" or self.show_all_months:
            return

        # 若當日明細浮窗已開啟，方向鍵 / WASD + Enter 改操控浮窗內項目（關閉 / 刪除 / 復原 / 換頁）
        if self._panel_date and self._panel_items:
            if direction in ("up", "left"):
                cur = 0 if self._panel_focus_idx is None else self._panel_focus_idx
                self._panel_focus_idx = (cur - 1) % len(self._panel_items)
                self._update_day_panel_highlights()
                return "break"
            if direction in ("down", "right"):
                cur = 0 if self._panel_focus_idx is None else self._panel_focus_idx
                self._panel_focus_idx = (cur + 1) % len(self._panel_items)
                self._update_day_panel_highlights()
                return "break"
            if event.keysym in ("Return", "space"):
                idx = 0 if self._panel_focus_idx is None else self._panel_focus_idx
                if 0 <= idx < len(self._panel_items):
                    _, _, action, _ = self._panel_items[idx]
                    action()
                return "break"
            return

        if direction is not None:
            deltas = {"up": -7, "down": 7, "left": -1, "right": 1}
            self._move_calendar_selection(deltas[direction])
            return "break"

        if event.keysym in ("Return", "space") and not isinstance(focused, (tk.Button, ttk.Button)):
            date_str = self.date_var.get().strip()
            if is_valid_iso_date(date_str) and date_str[:7] == self.current_month:
                self._panel_page = 0
                self._panel_focus_idx = None
                self._panel_date = date_str
                self._refresh_day_panel()
                return "break"

    def _build_charts_tab(self, parent: tk.Frame):
        top = tk.Frame(parent, bg="#FFFFFF", padx=14)
        top.pack(fill="x", pady=(10, 4))

        toggle_bar = tk.Frame(top, bg="#FFFFFF")
        toggle_bar.pack(side="left")

        self.chart_exp_wrap = tk.Frame(toggle_bar, bg="#FFFFFF", padx=2, pady=2)
        self.chart_exp_wrap.pack(side="left", padx=(0, 4))
        self.chart_exp_btn = tk.Button(
            self.chart_exp_wrap,
            text="支出報表",
            font=self.f_sm_b,
            bg=self.YELLOW,
            fg=self.INK,
            activebackground="#D9C38F",
            bd=0,
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=3,
            command=lambda: self._set_chart_type("支出"),
        )
        self.chart_exp_btn.pack()

        self.chart_inc_wrap = tk.Frame(toggle_bar, bg="#FFFFFF", padx=2, pady=2)
        self.chart_inc_wrap.pack(side="left")
        self.chart_inc_btn = tk.Button(
            self.chart_inc_wrap,
            text="收入報表",
            font=self.f_sm_b,
            bg=self.TILE_BG,
            fg=self.SUBTEXT,
            activebackground="#A5C0D4",
            bd=0,
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=3,
            command=lambda: self._set_chart_type("收入"),
        )
        self.chart_inc_btn.pack()

        tk.Label(
            top,
            text="↑↓/WS 選分類 · Enter 看明細 · ←→/AD 換月 · Esc 返回",
            font=self.f_xs,
            bg="#FFFFFF",
            fg=self.SUBTEXT,
        ).pack(side="right")

        container = tk.Frame(parent, bg="#FFFFFF", padx=14)
        container.pack(fill="both", expand=True, pady=(6, 12))

        left_chart = tk.Frame(container, bg="#FFFFFF")
        left_chart.pack(side="left", padx=(4, 18), anchor="n")

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
        self.donut_canvas.bind("<Button-1>", self._on_donut_click)

        # 右側支出排行圖例區改用單一 Canvas 直接繪圖 + ModernScrollbar（無巢狀子視窗延遲）
        legend_wrap = tk.Frame(container, bg="#FFFFFF")
        legend_wrap.pack(side="left", fill="both", expand=True, pady=(4, 0))

        self.chart_legend_canvas = tk.Canvas(legend_wrap, bg="#FFFFFF", highlightthickness=0)
        self.chart_legend_scrollbar = ModernScrollbar(legend_wrap, command=self.chart_legend_canvas.yview, bg="#FFFFFF")
        self.chart_legend_canvas.configure(yscrollcommand=self.chart_legend_scrollbar.set)

        self.chart_legend_scrollbar.pack(side="right", fill="y", padx=(4, 0))
        self.chart_legend_canvas.pack(side="left", fill="both", expand=True)

        self.chart_legend_canvas.bind("<Configure>", self._on_chart_legend_resize)
        self.chart_legend_canvas.bind("<Button-1>", self._on_chart_legend_click)
        self.chart_legend_canvas.bind("<Double-Button-1>", self._on_chart_legend_double_click)
        self.chart_legend_canvas.bind("<Motion>", self._on_chart_legend_motion)
        self.chart_legend_canvas.bind("<Leave>", lambda _e: self.chart_legend_canvas.configure(cursor=""))

    def _build_budgets_tab(self, parent: tk.Frame):
        top = tk.Frame(parent, bg="#FFFFFF", padx=14, pady=10)
        top.pack(fill="x")
        self.budget_header_lbl = tk.Label(top, text="每月分類預算", font=self.f_md_b, bg="#FFFFFF", fg=self.INK)
        self.budget_header_lbl.pack(side="left")
        tk.Label(
            top, text="上下 / WS 選取分類 · Enter 調整預算 · Esc 返回分頁列",
            font=self.f_xs, bg="#FFFFFF", fg=self.SUBTEXT,
        ).pack(side="right")

        scroll_wrap = tk.Frame(parent, bg="#FFFFFF", padx=12)
        scroll_wrap.pack(fill="both", expand=True, pady=(0, 10))

        self.budget_canvas = tk.Canvas(scroll_wrap, bg="#FFFFFF", highlightthickness=0)
        self.budget_canvas.bind("<Button-1>", lambda _e: self._focus_active_tab(), add="+")
        self.budget_scrollbar = ModernScrollbar(scroll_wrap, command=self.budget_canvas.yview, bg="#FFFFFF")
        self.budget_canvas.configure(yscrollcommand=self.budget_scrollbar.set)

        self.budget_scrollbar.pack(side="right", fill="y", padx=(4, 0))
        self.budget_canvas.pack(side="left", fill="both", expand=True)

        self.budget_list_frame = tk.Frame(self.budget_canvas, bg="#FFFFFF")
        self.budget_window_id = self.budget_canvas.create_window((0, 0), window=self.budget_list_frame, anchor="nw")

        self.budget_list_frame.bind(
            "<Configure>",
            lambda _e: self.budget_canvas.configure(scrollregion=self.budget_canvas.bbox("all")),
        )
        self.budget_canvas.bind("<Configure>", self._on_budget_canvas_resize)

    def _on_budget_canvas_resize(self, event):
        if event.width <= 10 or event.width == self._last_budget_canvas_w:
            return
        self._last_budget_canvas_w = event.width
        self.budget_canvas.itemconfigure(self.budget_window_id, width=event.width)

    # ==========================================
    # 右側：快速記帳面板
    # ==========================================
    def _build_right_panel(self):
        type_wrap = tk.Frame(self.right_col, bg="#FFFFFF", padx=14, pady=10)
        type_wrap.pack(fill="x")

        type_pill = tk.Frame(type_wrap, bg=self.TILE_BG, padx=3, pady=3)
        type_pill.pack(fill="x")
        type_pill.columnconfigure(0, weight=1, uniform="t")
        type_pill.columnconfigure(1, weight=1, uniform="t")

        exp_wrap = tk.Frame(type_pill, bg=self.TILE_BG, padx=2, pady=2)
        exp_wrap.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.btn_expense = tk.Button(
            exp_wrap, text="支出", font=self.f_lg_b, bd=0, relief="flat",
            cursor="hand2", pady=4, command=lambda: self._select_type("支出"),
        )
        self.btn_expense.pack(fill="both", expand=True)

        inc_wrap = tk.Frame(type_pill, bg=self.TILE_BG, padx=2, pady=2)
        inc_wrap.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        self.btn_income = tk.Button(
            inc_wrap, text="收入", font=self.f_lg_b, bd=0, relief="flat",
            cursor="hand2", pady=4, command=lambda: self._select_type("收入"),
        )
        self.btn_income.pack(fill="both", expand=True)

        self.amt_box = self._card_box(self.right_col, bg=self.YELLOW_SOFT, border="#EAE2CD")
        self.amt_box.pack(fill="x", padx=14, pady=(0, 10))

        amt_top = tk.Frame(self.amt_box, bg=self.YELLOW_SOFT)
        amt_top.pack(fill="x", padx=12, pady=(8, 0))
        self.amt_top_frame = amt_top

        self.amt_cat_badge = tk.Label(amt_top, text="🍔 飲食", font=self.f_sm_b,
                                      bg=self.YELLOW, fg="#FFFFFF", bd=0, padx=10, pady=2)
        self.amt_cat_badge.pack(side="left")

        self.amt_tip_lbl = tk.Label(amt_top, text="整數金額 · 支援 + -",
                                    font=self.f_xs, bg=self.YELLOW_SOFT, fg=self.SUBTEXT)
        self.amt_tip_lbl.pack(side="right")

        amt_row = tk.Frame(self.amt_box, bg=self.YELLOW_SOFT)
        amt_row.pack(fill="x", padx=12, pady=(2, 8))
        self.amt_row_frame = amt_row

        self.dollar_lbl = tk.Label(amt_row, text="$", font=self.f_num_dollar,
                                   bg=self.YELLOW_SOFT, fg=self.INK)
        self.dollar_lbl.pack(side="left")

        self.amount_entry = tk.Entry(
            amt_row, textvariable=self.amount_var, font=self.f_num_input,
            bg=self.YELLOW_SOFT, fg=self.INK, bd=0, relief="flat", justify="right",
        )
        self.amount_entry.pack(side="left", fill="x", expand=True)
        self.amount_entry.bind("<Return>", lambda _e: (self.handle_add_transaction(), "break")[1])
        self.amount_entry.bind("<Escape>", lambda _e: self._on_right_entry_escape(1, 0))

        self._preset_cats = ["飲食", "飲料", "交通", "娛樂", "日用", "購物", "薪資", "其他"]
        self._cat_hover_idx: int | None = None
        self._cat_canvas_size: tuple[int, int] = (0, 0)
        self.cat_canvas = tk.Canvas(self.right_col, bg="#FFFFFF", height=118, highlightthickness=0, cursor="hand2")
        self.cat_canvas.pack(fill="x", padx=14, pady=(0, 8))
        self.cat_canvas.bind("<Configure>", self._on_cat_canvas_resize)
        self.cat_canvas.bind("<Motion>", self._on_cat_canvas_motion)
        self.cat_canvas.bind("<Leave>", self._on_cat_canvas_leave)
        self.cat_canvas.bind("<Button-1>", self._on_cat_canvas_click)

        cat_rows = [[], []]
        for idx, name in enumerate(self._preset_cats):
            r, _c = divmod(idx, 4)
            cat_rows[r].append((self.cat_canvas, f"cat:{idx}", lambda n=name: self._select_category(n), f"分類：{name}"))

        meta = tk.Frame(self.right_col, bg="#FFFFFF", padx=14)
        meta.pack(fill="x", pady=(2, 4))

        r_date = tk.Frame(meta, bg="#FFFFFF")
        r_date.pack(fill="x", pady=3)
        tk.Label(r_date, text="日期", font=self.f_sm_b, bg="#FFFFFF", fg=self.SUBTEXT, width=4, anchor="w").pack(side="left")
        prev_d_wrap = tk.Frame(r_date, bg="#FFFFFF", padx=2, pady=2)
        prev_d_wrap.pack(side="left")
        tk.Button(prev_d_wrap, text="◀", font=self.f_sm, bg=self.TILE_BG, fg=self.INK,
                  activebackground=self.TILE_HOVER, bd=0, relief="flat", cursor="hand2",
                  width=2, command=lambda: self._shift_date(-1)).pack()
        date_wrap = tk.Frame(r_date, bg="#FFFFFF", padx=2, pady=2)
        date_wrap.pack(side="left", padx=2)
        self.date_entry = self._soft_entry(date_wrap, self.date_var, self.f_sm, width=11, justify="center")
        self.date_entry.pack(ipady=3)
        self.date_entry.bind("<KeyRelease>", self._on_date_entry_change)
        self.date_entry.bind("<FocusOut>", self._on_date_entry_change)
        self.date_entry.bind("<Escape>", lambda _e: self._on_right_entry_escape(4, 1))
        self.date_entry.bind("<Return>", lambda _e: self._on_right_entry_return(5, 0))
        next_d_wrap = tk.Frame(r_date, bg="#FFFFFF", padx=2, pady=2)
        next_d_wrap.pack(side="left")
        tk.Button(next_d_wrap, text="▶", font=self.f_sm, bg=self.TILE_BG, fg=self.INK,
                  activebackground=self.TILE_HOVER, bd=0, relief="flat", cursor="hand2",
                  width=2, command=lambda: self._shift_date(1)).pack()

        tk.Label(r_date, text="分類", font=self.f_sm_b, bg="#FFFFFF", fg=self.SUBTEXT).pack(side="left", padx=(8, 2))
        cat_e_wrap = tk.Frame(r_date, bg="#FFFFFF", padx=2, pady=2)
        cat_e_wrap.pack(side="left", fill="x", expand=True)
        self.category_entry = self._soft_entry(cat_e_wrap, self.category_var, self.f_sm, width=8)
        self.category_entry.pack(fill="x", expand=True, ipady=3)
        self.category_entry.bind("<Escape>", lambda _e: self._on_right_entry_escape(4, 3))
        self.category_entry.bind("<Return>", lambda _e: self._on_right_entry_return(5, 0))

        r_note = tk.Frame(meta, bg="#FFFFFF")
        r_note.pack(fill="x", pady=(4, 2))
        tk.Label(r_note, text="備註", font=self.f_sm_b, bg="#FFFFFF", fg=self.SUBTEXT, width=4, anchor="w").pack(side="left")
        note_e_wrap = tk.Frame(r_note, bg="#FFFFFF", padx=2, pady=2)
        note_e_wrap.pack(side="left", fill="x", expand=True)
        self.note_entry = self._soft_entry(note_e_wrap, self.note_var, self.f_sm)
        self.note_entry.pack(fill="x", expand=True, ipady=3)
        self.note_entry.bind("<Escape>", lambda _e: self._on_right_entry_escape(5, 0))
        self.note_entry.bind("<Return>", lambda _e: self._on_right_entry_return(6, 0))

        self.tag_chips_frame = tk.Frame(self.right_col, bg="#FFFFFF", padx=14)
        self.tag_chips_frame.pack(fill="x", pady=(3, 6))

        self._keypad_grid = [
            [("C", "red"), ("+50", "neutral"), ("+100", "neutral"), ("⌫", "red")],
            [("7", "tile"), ("8", "tile"), ("9", "tile"), ("+", "neutral")],
            [("4", "tile"), ("5", "tile"), ("6", "tile"), ("-", "neutral")],
            [("1", "tile"), ("2", "tile"), ("3", "tile"), ("=", "neutral")],
            [("0", "tile"), ("00", "tile"), ("000", "tile"), ("OK", "ok")],
        ]
        self._keypad_hover: tuple[int, int] | None = None
        self._keypad_pressed: tuple[int, int] | None = None
        self._keypad_size: tuple[int, int] = (0, 0)
        self._ok_bg: str = self.YELLOW
        self.keypad_canvas = tk.Canvas(self.right_col, bg="#FFFFFF", height=230, highlightthickness=0, cursor="hand2")
        self.keypad_canvas.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.keypad_canvas.bind("<Configure>", self._on_keypad_canvas_resize)
        self.keypad_canvas.bind("<Motion>", self._on_keypad_canvas_motion)
        self.keypad_canvas.bind("<Leave>", self._on_keypad_canvas_leave)
        self.keypad_canvas.bind("<Button-1>", self._on_keypad_canvas_press)
        self.keypad_canvas.bind("<ButtonRelease-1>", self._on_keypad_canvas_release)

        pad_rows = [[] for _ in range(5)]
        for r_idx, row_defs in enumerate(self._keypad_grid):
            for c_idx, (key, kind_tag) in enumerate(row_defs):
                if kind_tag == "ok":
                    action = self.handle_add_transaction
                    label = "確認新增 OK"
                else:
                    action = lambda k=key: self._on_keypad(k)
                    label = f"按鍵 {key}"
                pad_rows[r_idx].append((self.keypad_canvas, f"pad:{r_idx}:{c_idx}", action, label))

        self._right_rows_top = [
            [
                (exp_wrap, self.TILE_BG, lambda: self._select_type("支出"), "支出"),
                (inc_wrap, self.TILE_BG, lambda: self._select_type("收入"), "收入"),
            ],
            [
                (self.amt_box, "amt_box", lambda: self._focus_right_entry(self.amount_entry, "金額"), "金額輸入框"),
            ],
            cat_rows[0],
            cat_rows[1],
            [
                (prev_d_wrap, "#FFFFFF", lambda: self._shift_date(-1), "前一天"),
                (date_wrap, "#FFFFFF", lambda: self._focus_right_entry(self.date_entry, "日期"), "日期輸入框"),
                (next_d_wrap, "#FFFFFF", lambda: self._shift_date(1), "後一天"),
                (cat_e_wrap, "#FFFFFF", lambda: self._focus_right_entry(self.category_entry, "分類"), "分類輸入框"),
            ],
            [
                (note_e_wrap, "#FFFFFF", lambda: self._focus_right_entry(self.note_entry, "備註"), "備註輸入框"),
            ],
        ]
        self._right_rows_bottom = pad_rows

    # ==========================================
    # 互動控制邏輯
    # ==========================================
    def _focus_active_tab(self):
        if self.active_tab == "calendar" and not self.show_all_months:
            self._focus_calendar()
            return
        if self.active_tab == "budgets":
            self._focus_budgets(self._budget_selected_idx)
            return
        if self.active_tab == "records":
            self._focus_records(self._records_focus)
            return
        if self.active_tab == "charts":
            self._focus_charts(self._chart_selected_idx, self._chart_focus_area)
            return
        self._nav_zone = "tabs"
        if self.active_tab in self.tab_order:
            self._focused_tab_idx = self.tab_order.index(self.active_tab)
        if self.active_tab in self.tab_frames:
            self.tab_frames[self.active_tab].focus_set()
        self._update_all_nav_highlights()
        self._sync_calendar_ime(force=True)

    def _switch_tab(self, key: str, enter_content: bool = True):
        self._close_day_panel()
        self.active_tab = key
        if key in self.tab_order:
            self._focused_tab_idx = self.tab_order.index(key)
        for k, frame in self.tab_frames.items():
            frame.pack_forget()
        self.tab_frames[key].pack(fill="both", expand=True)

        self._refresh_all()
        if enter_content:
            self._enter_tab_content(key)
            if key == "calendar" and not self.show_all_months:
                self._on_cal_resize()
        else:
            self._nav_zone = "tabs"
            if key in self.tab_frames:
                self.tab_frames[key].focus_set()
            self._update_all_nav_highlights()
            self._sync_calendar_ime(force=True)

    def _select_type(self, trans_type: str):
        self.trans_type_var.set(trans_type)
        if trans_type == "支出":
            self.btn_expense.configure(bg=self.YELLOW, fg=self.INK)
            self.btn_income.configure(bg=self.TILE_BG, fg=self.SUBTEXT)
            theme_bg, accent, box_border = self.YELLOW_SOFT, self.YELLOW, "#EAE2CD"
            if self.category_var.get() == "薪資":
                self._select_category("飲食")
        else:
            self.btn_income.configure(bg=self.BLUE, fg=self.INK)
            self.btn_expense.configure(bg=self.TILE_BG, fg=self.SUBTEXT)
            theme_bg, accent, box_border = self.BLUE_SOFT, self.BLUE, "#D6E2EC"
            self._select_category("薪資")

        self._amt_box_border = box_border
        self.amt_box.configure(bg=theme_bg, highlightbackground=box_border, highlightcolor=box_border)
        for w in (self.amt_top_frame, self.amt_tip_lbl, self.amt_row_frame, self.dollar_lbl, self.amount_entry):
            w.configure(bg=theme_bg)
        self._ok_bg = accent
        self._update_right_nav_styles()

    def _select_category(self, name: str):
        self.category_var.set(name)
        cat = self.account.get_or_create_category(name)
        self.amt_cat_badge.configure(text=f"{cat.icon} {cat.name}", bg=cat.color, fg="#FFFFFF")
        self._paint_cat_canvas()
        self._render_tag_chips(name)

    def _paint_cat_canvas(self):
        if not hasattr(self, "cat_canvas"):
            return
        c = self.cat_canvas
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 8 or h <= 8:
            w, h = 360, 118
        c.delete("all")
        cw, ch = w / 4.0, h / 2.0
        sel_kind = self._right_selected_kind()
        active_cat = self.category_var.get()
        for idx, name in enumerate(self._preset_cats):
            r, col = divmod(idx, 4)
            x0 = col * cw + 3
            y0 = r * ch + 3
            x1 = (col + 1) * cw - 3
            y1 = (r + 1) * ch - 3
            cat = self.account.categories[name]
            is_active = (name == active_cat)
            is_hover = (self._cat_hover_idx == idx)
            bg = cat.color if is_active else (self.TILE_HOVER if is_hover else self.TILE_BG)
            fg = "#FFFFFF" if is_active else self.INK
            if sel_kind == f"cat:{idx}":
                c.create_rectangle(x0 - 2, y0 - 2, x1 + 2, y1 + 2, fill="#FFFFFF", outline="#AD8846", width=2)
            c.create_rectangle(x0, y0, x1, y1, fill=bg, outline="")
            c.create_text(
                (x0 + x1) / 2.0, (y0 + y1) / 2.0,
                text=f"{cat.icon}\n{cat.name}", font=self.f_sm_b, fill=fg, justify="center",
            )

    def _cat_cell_at(self, x: float, y: float) -> tuple[int, str] | None:
        w = self.cat_canvas.winfo_width()
        h = self.cat_canvas.winfo_height()
        if w <= 8 or h <= 8 or not (0 <= x < w and 0 <= y < h):
            return None
        col = max(0, min(3, int(x / (w / 4.0))))
        r = max(0, min(1, int(y / (h / 2.0))))
        idx = r * 4 + col
        return (idx, self._preset_cats[idx])

    def _on_cat_canvas_resize(self, event):
        size = (event.width, event.height)
        if size == self._cat_canvas_size or event.width <= 8 or event.height <= 8:
            return
        self._cat_canvas_size = size
        self._paint_cat_canvas()

    def _on_cat_canvas_motion(self, event):
        hit = self._cat_cell_at(event.x, event.y)
        idx = hit[0] if hit is not None else None
        if idx != self._cat_hover_idx:
            self._cat_hover_idx = idx
            self._paint_cat_canvas()

    def _on_cat_canvas_leave(self, _event=None):
        if self._cat_hover_idx is not None:
            self._cat_hover_idx = None
            self._paint_cat_canvas()

    def _on_cat_canvas_click(self, event):
        hit = self._cat_cell_at(event.x, event.y)
        if hit is not None:
            self._select_category(hit[1])

    def _paint_keypad_canvas(self):
        if not hasattr(self, "keypad_canvas"):
            return
        c = self.keypad_canvas
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 8 or h <= 8:
            w, h = 360, 230
        c.delete("all")
        cw, ch = w / 4.0, h / 5.0
        sel_kind = self._right_selected_kind()
        is_yellow_ok = (self._ok_bg == self.YELLOW)
        for r_idx, row_defs in enumerate(self._keypad_grid):
            for c_idx, (key, kind_tag) in enumerate(row_defs):
                x0 = c_idx * cw + 3
                y0 = r_idx * ch + 3
                x1 = (c_idx + 1) * cw - 3
                y1 = (r_idx + 1) * ch - 3
                is_press = (self._keypad_pressed == (r_idx, c_idx))
                is_hover = (self._keypad_hover == (r_idx, c_idx))
                if kind_tag == "red":
                    bg = "#EED8D8" if is_press else ("#F3E2E2" if is_hover else self.RED_SOFT)
                    fg = self.RED_TEXT
                    kfont = self.f_md_b
                elif kind_tag == "neutral":
                    bg = "#E2DFD6" if is_press else (self.TILE_HOVER if is_hover else self.NEUTRAL)
                    fg = self.INK
                    kfont = self.f_md_b if r_idx == 0 else self.f_num_key
                elif kind_tag == "ok":
                    bg = ("#D9C38F" if is_yellow_ok else "#A5C0D4") if is_press else (
                        ("#DFCA97" if is_yellow_ok else "#AEC7DA") if is_hover else self._ok_bg
                    )
                    fg = self.INK
                    kfont = self.f_num_ok
                else:
                    bg = "#E2DFD6" if is_press else (self.TILE_HOVER if is_hover else self.TILE_BG)
                    fg = self.INK
                    kfont = self.f_num_key
                if sel_kind == f"pad:{r_idx}:{c_idx}":
                    c.create_rectangle(x0 - 2, y0 - 2, x1 + 2, y1 + 2, fill="#FFFFFF", outline="#AD8846", width=2)
                c.create_rectangle(x0, y0, x1, y1, fill=bg, outline="")
                c.create_text((x0 + x1) / 2.0, (y0 + y1) / 2.0, text=key, font=kfont, fill=fg)

    def _keypad_cell_at(self, x: float, y: float) -> tuple[int, int] | None:
        w = self.keypad_canvas.winfo_width()
        h = self.keypad_canvas.winfo_height()
        if w <= 8 or h <= 8 or not (0 <= x < w and 0 <= y < h):
            return None
        col = max(0, min(3, int(x / (w / 4.0))))
        r = max(0, min(4, int(y / (h / 5.0))))
        return (r, col)

    def _on_keypad_canvas_resize(self, event):
        size = (event.width, event.height)
        if size == self._keypad_size or event.width <= 8 or event.height <= 8:
            return
        self._keypad_size = size
        self._paint_keypad_canvas()

    def _on_keypad_canvas_motion(self, event):
        cell = self._keypad_cell_at(event.x, event.y)
        if cell != self._keypad_hover:
            self._keypad_hover = cell
            self._paint_keypad_canvas()

    def _on_keypad_canvas_leave(self, _event=None):
        if self._keypad_hover is not None or self._keypad_pressed is not None:
            self._keypad_hover = None
            self._keypad_pressed = None
            self._paint_keypad_canvas()

    def _on_keypad_canvas_press(self, event):
        cell = self._keypad_cell_at(event.x, event.y)
        if cell != self._keypad_pressed:
            self._keypad_pressed = cell
            self._paint_keypad_canvas()

    def _on_keypad_canvas_release(self, event):
        pressed = self._keypad_pressed
        self._keypad_pressed = None
        cell = self._keypad_cell_at(event.x, event.y)
        self._paint_keypad_canvas()
        if pressed is not None and cell == pressed:
            key, kind_tag = self._keypad_grid[cell[0]][cell[1]]
            if kind_tag == "ok":
                self.handle_add_transaction()
            else:
                self._on_keypad(key)

    def _render_tag_chips(self, cat_name: str):
        for w in self.tag_chips_frame.winfo_children():
            w.destroy()
        self._right_tag_row = []
        tags = self.account.get_tags_for_category(cat_name)
        if not tags:
            self._update_right_nav_styles()
            return
        tk.Label(self.tag_chips_frame, text="常用：", font=self.f_xs, bg="#FFFFFF", fg=self.SUBTEXT).pack(side="left")
        for tag in tags[:4]:
            t_wrap = tk.Frame(self.tag_chips_frame, bg="#FFFFFF", padx=2, pady=2)
            t_wrap.pack(side="left")
            tk.Button(
                t_wrap, text=f"#{tag}", font=self.f_xs,
                bg=self.TILE_BG, fg=self.INK, activebackground=self.TILE_HOVER,
                bd=0, relief="flat", cursor="hand2", padx=8, pady=2,
                command=lambda t=tag: self.note_var.set(t),
            ).pack()
            self._right_tag_row.append((t_wrap, "#FFFFFF", lambda t=tag: self.note_var.set(t), f"常用 #{tag}"))
        self._update_right_nav_styles()

    def _shift_month(self, delta: int):
        self.show_all_months = False
        y, m = map(int, self.current_month.split("-"))
        m += delta
        if m < 1:
            y, m = y - 1, 12
        elif m > 12:
            y, m = y + 1, 1
        if not 1 <= y <= 9999:
            self.status_var.set("已到可選月份的邊界")
            return
        self.current_month = f"{y:04d}-{m:02d}"
        self._refresh_all()
        if self.active_tab == "calendar":
            self._focus_calendar()
        elif self.active_tab == "charts" and self._nav_zone == "charts":
            self._focus_charts(self._chart_selected_idx, self._chart_focus_area)

    def _toggle_all_months(self):
        if self.show_all_months:
            self.show_all_months = False
            self.current_month = datetime.today().strftime("%Y-%m")
        else:
            self.show_all_months = True
        self._refresh_all()
        if not self.show_all_months and self.active_tab == "calendar":
            self._focus_calendar()
        else:
            self._focus_active_tab()

    def _update_calendar_selection(self, new_date: str):
        old_date = self._last_selected_cal_date
        if old_date in self._cal_cells:
            item, bg = self._cal_cells[old_date]
            self.cal_grid_frame.itemconfigure(item, fill=bg, outline=self.BORDER, width=1)
        if new_date in self._cal_cells:
            item, _ = self._cal_cells[new_date]
            self.cal_grid_frame.itemconfigure(item, fill=self.YELLOW_SOFT, outline="#AD8846", width=2)
        self._last_selected_cal_date = new_date
        self._refresh_day_panel()

    def _sync_calendar_to_date(self, date_str: str):
        """同月原地無閃爍移動選取框；跨月時自動切換月份"""
        if self.show_all_months:
            self._last_selected_cal_date = date_str
            return
        new_month = date_str[:7]
        if new_month != self.current_month:
            self.current_month = new_month
            self._refresh_all()
        elif self.active_tab != "calendar":
            return
        elif self._cal_rendered_month == new_month and self._cal_cells:
            self._update_calendar_selection(date_str)
        else:
            self._render_calendar()

    def _shift_date(self, delta: int):
        raw = self.date_var.get().strip()
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            dt = datetime.today()
        try:
            new_str = (dt + timedelta(days=delta)).date().isoformat()
        except OverflowError:
            self.status_var.set("已到可選日期的邊界")
            return
        self.date_var.set(new_str)
        self._sync_calendar_to_date(new_str)

    def _on_date_entry_change(self, _event=None):
        date_str = self.date_var.get().strip()
        if date_str == self._last_selected_cal_date:
            return
        if is_valid_iso_date(date_str):
            self._sync_calendar_to_date(date_str)

    def _pick_calendar_date(self, date_str: str):
        self.date_var.set(date_str)
        self.status_var.set(f"已選取 {date_str}")
        self._update_calendar_selection(date_str)

    @staticmethod
    def _strip_amount_leading_zeros(text: str) -> str:
        """移除金額算式中各數值段的前導零（例如 0、00、05、100+05），保留 0.5 供錯誤提示。"""
        return re.sub(r"(^|[+-])0+(?=\d|$)", r"\1", text)

    def _on_amount_var_changed(self, *_args):
        if self._normalizing_amount:
            return
        raw = self.amount_var.get()
        cleaned = self._strip_amount_leading_zeros(raw)
        if cleaned == raw:
            return
        entry = getattr(self, "amount_entry", None)
        cursor = None
        if entry is not None and entry.winfo_exists():
            try:
                pos = entry.index(tk.INSERT)
                cursor = min(len(cleaned), len(self._strip_amount_leading_zeros(raw[:pos])))
            except tk.TclError:
                cursor = None
        self._normalizing_amount = True
        try:
            self.amount_var.set(cleaned)
        finally:
            self._normalizing_amount = False
        if entry is not None and cursor is not None and entry.winfo_exists():
            try:
                entry.icursor(cursor)
            except tk.TclError:
                pass

    def _on_inline_budget_var_changed(self, *_args):
        if self._normalizing_budget or self._inline_budget_var is None:
            return
        raw = self._inline_budget_var.get()
        cleaned = re.sub(r"^0+(?=\d)", "", raw)
        if cleaned == raw:
            return
        entry = getattr(self, "_inline_budget_entry", None)
        cursor = None
        if entry is not None and entry.winfo_exists():
            try:
                pos = entry.index(tk.INSERT)
                cursor = max(0, pos - (len(raw) - len(cleaned)))
            except tk.TclError:
                cursor = None
        self._normalizing_budget = True
        try:
            self._inline_budget_var.set(cleaned)
        finally:
            self._normalizing_budget = False
        if entry is not None and cursor is not None and entry.winfo_exists():
            try:
                entry.icursor(cursor)
            except tk.TclError:
                pass

    def _eval_amount_expr(self, expr: str) -> int:
        """嚴格驗證整數加減算式：拒絕小數與未完成算式（例如 100+、0.4）"""
        cleaned = expr.replace(",", "").replace(" ", "")
        if not cleaned:
            raise ValueError("請輸入金額。")
        if "." in cleaned:
            raise ValueError("僅支援整數金額，請勿輸入小數點。")
        if cleaned[-1] in ("+", "-"):
            raise ValueError("算式尚未完成，結尾不可為 + 或 -。")
        if not re.fullmatch(r"[+-]?\d+(?:[+-]\d+)*", cleaned):
            raise ValueError("算式格式錯誤，請輸入整數或正確的加減算式。")
        tokens = re.findall(r"[+-]?\d+", cleaned)
        return sum(int(tok) for tok in tokens)

    def _on_keypad(self, key: str):
        cur = self.amount_var.get().strip()
        if key == "C":
            self.amount_var.set("")
        elif key == "⌫":
            self.amount_var.set(cur[:-1])
        elif key in ("+50", "+100"):
            add_val = int(key[1:])
            if not cur:
                self.amount_var.set(str(add_val))
                return
            try:
                base = self._eval_amount_expr(cur)
            except ValueError as e:
                messagebox.showerror("金額錯誤", str(e))
                return
            self.amount_var.set(str(base + add_val))
        elif key == "=":
            try:
                val = self._eval_amount_expr(cur)
                self.amount_var.set("" if val == 0 else str(val))
            except ValueError as e:
                messagebox.showerror("算式錯誤", str(e))
        elif key in ("+", "-"):
            if cur and cur[-1] not in ("+", "-"):
                self.amount_var.set(cur + key)
        else:
            # 切出目前輸入段，防止前導零（例如 0、00、000、05）
            m = re.search(r"[+-]([^+-]*)$", cur)
            if m:
                prefix = cur[: m.start() + 1]
                seg = m.group(1)
            else:
                prefix = ""
                seg = cur

            is_zero_seg = (seg == "0") or (bool(seg) and set(seg) == {"0"})

            if key in ("0", "00", "000"):
                if is_zero_seg or not seg:
                    return
                self.amount_var.set(cur + key)
            else:
                if is_zero_seg:
                    self.amount_var.set(prefix + key)
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
        if not is_valid_iso_date(date):
            messagebox.showerror("日期錯誤", f"「{date}」是不存在的日期，請確認該月份天數後重新輸入。")
            return

        try:
            amount = self._eval_amount_expr(self.amount_var.get())
            if amount <= 0:
                raise ValueError("請輸入大於 0 的整數金額。")
        except ValueError as e:
            messagebox.showerror("金額錯誤", str(e))
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
            self.status_var.set(f"超支提醒：{warning}")
            messagebox.showwarning("預算超支", warning)
        else:
            label = t.get_reason()
            self.status_var.set(f"已新增 {date} {label} ${fmt_num(amount)}")
        if self._nav_zone == "right":
            self._focus_right_panel(row=1, col=0)

    def handle_delete_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("提示", "請先點選要刪除的紀錄。")
            self._sync_calendar_ime(force=True)
            return
        idx = int(selected[0])
        if 0 <= idx < len(self._displayed_rows):
            target = self._displayed_rows[idx]
            self.account.delete_transaction(target)
            self._refresh_all()
            children = self.tree.get_children()
            if children:
                next_iid = children[min(idx, len(children) - 1)]
                self.tree.selection_set(next_iid)
                self.tree.focus(next_iid)
                self.tree.see(next_iid)
            self.status_var.set(f"已刪除 {target.date} {target.get_reason()} ${fmt_num(target.amount)}")
            self._update_all_nav_highlights()
            self._sync_calendar_ime(force=True)

    def handle_clear_all_data(self):
        if not self.account.transactions:
            self.status_var.set("目前沒有可清除的紀錄")
            return
        confirm = messagebox.askyesno(
            "清除資料",
            f"確定要清除目前全部 {len(self.account.transactions)} 筆收支紀錄嗎？\n（分類預算上限會保留）",
        )
        if not confirm:
            return
        for job in self._undo_jobs.values():
            self.root.after_cancel(job)
        self._undo_jobs.clear()
        self._undo_order.clear()
        self.account.clear_transactions()
        self.search_var.set("")
        self._refresh_all()
        self.status_var.set("已清除全部紀錄")

    def handle_export_csv(self):
        active_filter = "全部" if self.show_all_months else self.current_month
        rows = self.account.get_filtered_transactions(active_filter, self.search_var.get())
        if not rows:
            messagebox.showinfo("提示", "目前篩選條件下沒有紀錄可匯出。")
            return
        suffix = "all" if self.show_all_months else self.current_month
        filepath = filedialog.asksaveasfilename(
            title="匯出 CSV",
            defaultextension=".csv",
            initialfile=f"budget_{suffix}.csv",
            filetypes=[("CSV 檔案", "*.csv")],
        )
        if not filepath:
            return
        try:
            self.account.export_to_csv(filepath, transactions=rows)
            self.status_var.set(f"已匯出 {len(rows)} 筆紀錄：{filepath}")
            messagebox.showinfo("匯出完成", f"已匯出 {len(rows)} 筆紀錄至：\n{filepath}")
        except OSError as e:
            messagebox.showerror("匯出失敗", str(e))

    def _toggle_inline_budget_editor(self, cat_name: str):
        if cat_name in self._budget_order:
            self._budget_selected_idx = self._budget_order.index(cat_name)
        if self.editing_budget_cat == cat_name:
            self.editing_budget_cat = None
        else:
            self.editing_budget_cat = cat_name
        active_filter = "全部" if self.show_all_months else self.current_month
        self._render_budget_cards(self.account.get_category_expenses(active_filter))
        if self.editing_budget_cat is None:
            self._focus_budgets(self._budget_selected_idx)
        else:
            self._scroll_budget_card_into_view(cat_name)

    def _nudge_inline_budget(self, delta: int):
        if self._inline_budget_var is None:
            return
        raw = self._inline_budget_var.get().strip().replace(",", "")
        cur = int(raw) if raw.isdigit() else 0
        self._inline_budget_var.set(str(max(0, cur + delta)))

    def _save_inline_budget(self, cat_name: str):
        if self._inline_budget_var is None:
            return
        raw = self._inline_budget_var.get().strip().replace(",", "")
        if not re.fullmatch(r"\d+", raw):
            self.status_var.set("請輸入大於等於 0 的整數預算")
            return
        val = int(raw)
        self.account.set_category_budget(cat_name, val)
        self.editing_budget_cat = None
        self._refresh_all()
        self._focus_budgets(self._budget_selected_idx)
        self.status_var.set(f"「{cat_name}」月預算已設為 ${fmt_num(val)}")

    # ==========================================
    # 畫面更新與各分頁渲染
    # ==========================================
    def _refresh_all(self):
        active_filter = "全部" if self.show_all_months else self.current_month
        self.month_lbl.configure(text="全部月份" if self.show_all_months else self.current_month)
        self.all_month_btn.configure(
            text="回當月" if self.show_all_months else "全部月份",
            bg=self.BLUE if self.show_all_months else self.TILE_BG,
        )
        self.bal_title_lbl.configure(text="總結餘" if self.show_all_months else "本期結餘")

        income, expense, balance = self.account.get_summary(active_filter)
        self._last_inc, self._last_exp = income, expense

        self.expense_lbl.configure(text=fmt_currency(expense))
        self.income_lbl.configure(text=fmt_currency(income))
        self.balance_lbl.configure(text=fmt_currency(balance))

        if balance < 0:
            self.bal_box.configure(bg=self.RED_SOFT, highlightbackground="#ECD7D7", highlightcolor="#ECD7D7")
            self.bal_title_lbl.configure(bg=self.RED_SOFT, fg=self.RED_TEXT)
            self.balance_lbl.configure(bg=self.RED_SOFT, fg=self.RED_TEXT)
            self.ratio_hint_lbl.configure(text="支出大於收入", bg=self.RED_SOFT, fg=self.RED_TEXT)
        else:
            self.bal_box.configure(bg=self.TILE_BG, highlightbackground=self.BORDER, highlightcolor=self.BORDER)
            self.bal_title_lbl.configure(bg=self.TILE_BG, fg=self.SUBTEXT)
            self.balance_lbl.configure(bg=self.TILE_BG, fg=self.INK)
            if income > 0:
                pct = expense / income * 100
                self.ratio_hint_lbl.configure(text=f"支出佔收入 {pct:.0f}%", bg=self.TILE_BG, fg=self.SUBTEXT)
            else:
                self.ratio_hint_lbl.configure(text="收支總覽", bg=self.TILE_BG, fg=self.SUBTEXT)

        self._draw_ratio_bar()
        if self.active_tab == "records":
            self._refresh_records_table()
        elif self.active_tab == "calendar":
            self._render_calendar()
        elif self.active_tab == "charts":
            totals = self.account.get_category_totals(active_filter, self.chart_type)
            chart_key = (self.show_all_months, self.current_month, self.chart_type, tuple(totals.items()))
            if chart_key != getattr(self, "_last_chart_key", None):
                self._draw_donut_and_legend(totals)
                self._last_chart_key = chart_key
        elif self.active_tab == "budgets":
            self._render_budget_cards(self.account.get_category_expenses(active_filter))

    def _draw_ratio_bar(self):
        c = self.ratio_canvas
        w = max(c.winfo_width(), 10)
        key = (w, self._last_inc, self._last_exp)
        if key == self._last_ratio_key:
            return
        self._last_ratio_key = key
        c.delete("all")
        total = self._last_inc + self._last_exp
        if total <= 0:
            return
        exp_w = int((self._last_exp / total) * w)
        exp_color = self.RED if self._last_exp > self._last_inc else self.YELLOW
        if exp_w > 0:
            c.create_rectangle(0, 0, exp_w, 12, fill=exp_color, outline="")
        if exp_w < w:
            c.create_rectangle(exp_w, 0, w, 12, fill=self.BLUE, outline="")
        if 0 < exp_w < w:
            c.create_line(exp_w, 0, exp_w, 12, fill="#FFFFFF", width=2)

    def _refresh_records_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        active_filter = "全部" if self.show_all_months else self.current_month
        rows = self.account.get_filtered_transactions(active_filter, self.search_var.get())
        self._displayed_rows = rows
        self.record_count_lbl.configure(text=f"共 {len(rows)} 筆")
        for idx, t in enumerate(rows):
            sign = "-" if t.trans_type == "支出" else "+"
            tag = "expense" if t.trans_type == "支出" else "income"
            self.tree.insert(
                "", "end", iid=str(idx),
                values=(t.date, t.trans_type, f"{t.category.icon} {t.category.name}", t.note or "—", f"{sign}${fmt_num(t.amount)}"),
                tags=(tag,),
            )

    def _close_day_panel(self):
        self._panel_date = ""
        self._panel_items = []
        self._panel_focus_idx = None
        self.day_panel.place_forget()
        if self.active_tab == "calendar" and not self.show_all_months and self._nav_zone == "calendar":
            self.cal_grid_frame.focus_set()
            self._sync_calendar_ime(force=True)

    def _update_day_panel_highlights(self):
        if not self._panel_items:
            return
        idx = 0 if self._panel_focus_idx is None else max(0, min(self._panel_focus_idx, len(self._panel_items) - 1))
        self._panel_focus_idx = idx
        for i, (wrap, default_bg, _action, label) in enumerate(self._panel_items):
            if wrap.winfo_exists():
                wrap.configure(bg="#AD8846" if i == idx else default_bg)
        label = self._panel_items[idx][3]
        self.status_var.set(f"{self._panel_date} 明細：已選取「{label}」（↑↓←→ / WASD 選擇，Enter 執行，Esc 關閉）")

    def _dismiss_day_panel(self, event):
        if not self._panel_date or event.widget is self.cal_grid_frame:
            return
        widget = event.widget
        while widget is not None:
            if widget is self.day_panel:
                return
            widget = getattr(widget, "master", None)
        self._close_day_panel()

    def _position_day_panel(self):
        cell = self._cal_cells.get(self._panel_date)
        if not cell:
            return
        canvas = self.cal_grid_frame
        left, top, right, _ = canvas.coords(cell[0])
        width = min(360, canvas.winfo_width())
        height = self.day_panel.winfo_reqheight()
        x = right + 4 if right + 4 + width <= canvas.winfo_width() else left - width - 4
        y = min(top, canvas.winfo_height() - height)
        self.day_panel.place(x=max(0, x), y=max(0, y), width=width)
        self.day_panel.lift()

    def _page_day_panel(self, step):
        self._panel_page += step
        self._panel_focus_idx = None
        self._refresh_day_panel()

    def _refresh_day_panel(self):
        date = self._panel_date
        if not date:
            return
        if self.show_all_months or date != self.date_var.get() or date[:7] != self.current_month:
            self._close_day_panel()
            return
        panel = self.day_panel
        for child in panel.winfo_children():
            child.destroy()
        self._panel_items = []
        rows = self.account.get_transactions_on_date(date)
        count = len(rows)
        if self._undo_jobs:
            order = {t: i for i, t in enumerate(self._undo_order)}
            rows.extend(t for t in self._undo_jobs if t.date == date)
            rows.sort(key=lambda t: (t.trans_type != "支出", -t.amount, order.get(t, len(order))))
        header = tk.Frame(panel, bg="white")
        header.pack(fill="x")
        tk.Label(header, text=f"{date}　·　{count} 筆", font=self.f_sm_b,
                 bg="white", fg=self.INK).pack(side="left")
        close_wrap = tk.Frame(header, bg="white", padx=2, pady=2)
        close_wrap.pack(side="right")
        tk.Button(close_wrap, text="關閉", command=self._close_day_panel, bg="white",
                  fg=self.SUBTEXT, bd=0, font=self.f_xs, padx=4, pady=1, cursor="hand2").pack()
        add_wrap = tk.Frame(header, bg="white", padx=2, pady=2)
        add_wrap.pack(side="right", padx=(0, 4))
        tk.Button(add_wrap, text="新增", command=self._start_add_from_day_panel, bg=self.YELLOW,
                  fg=self.INK, activebackground="#D9C38F", bd=0, font=self.f_xs,
                  padx=8, pady=1, cursor="hand2").pack()
        self._panel_items.append((add_wrap, "white", self._start_add_from_day_panel, "新增"))
        self._panel_items.append((close_wrap, "white", self._close_day_panel, "關閉"))
        if not rows:
            tk.Label(panel, text="當天尚無收支紀錄", bg="white", fg=self.SUBTEXT,
                     font=self.f_sm, anchor="w").pack(fill="x", pady=6)

        page_size = 3
        last = max(0, (len(rows) - 1) // page_size)
        self._panel_page = min(max(self._panel_page, 0), last)
        start = self._panel_page * page_size
        visible_rows = rows[start:start + page_size]
        for t in visible_rows:
            deleted = t in self._undo_jobs
            bg = self.TILE_BG if deleted else "white"
            row = tk.Frame(panel, bg=bg)
            row.pack(fill="x", pady=(4, 0))
            action = self._undo_calendar_row if deleted else self._delete_calendar_row
            btn_text = "復原" if deleted else "刪除"
            btn_wrap = tk.Frame(row, bg=bg, padx=2, pady=2)
            btn_wrap.pack(side="right")
            cmd = lambda t=t, fn=action: fn(t)
            tk.Button(btn_wrap, text=btn_text, font=self.f_sm_b, bd=0,
                      padx=8, pady=3, cursor="hand2", bg=self.BLUE_SOFT if deleted else self.RED_SOFT,
                      fg=self.CAL_INC_TEXT if deleted else self.RED_TEXT,
                      command=cmd).pack()
            self._panel_items.append((btn_wrap, bg, cmd, f"{btn_text} {t.get_reason()}"))
            amount = ("−$" if t.trans_type == "支出" else "+$") + fmt_num(t.amount)
            tk.Label(row, text=amount, bg=bg, font=self.f_sm_b,
                     fg=self.CAL_EXP_TEXT if t.trans_type == "支出" else self.CAL_INC_TEXT
                     ).pack(side="right", padx=6)
            text = ("已刪除　" if deleted else "") + t.get_reason()
            tk.Label(row, text=text, anchor="w", bg=bg, fg=self.INK, font=self.f_sm
                     ).pack(side="left", fill="x", expand=True)
        if last:
            nav = tk.Frame(panel, bg="white")
            nav.pack(fill="x", pady=(4, 0))
            for step, label in ((-1, "上一頁"), (1, "下一頁")):
                enabled = 0 <= self._panel_page + step <= last
                nav_wrap = tk.Frame(nav, bg="white", padx=2, pady=2)
                nav_wrap.pack(side="left")
                nav_cmd = lambda n=step: self._page_day_panel(n)
                tk.Button(nav_wrap, text=label, bd=0, bg="white", font=self.f_xs,
                          state="normal" if enabled else "disabled",
                          cursor="hand2" if enabled else "",
                          command=nav_cmd).pack()
                if enabled:
                    self._panel_items.append((nav_wrap, "white", nav_cmd, label))
            tk.Label(nav, text=f"{self._panel_page + 1} / {last + 1}", bg="white",
                     fg=self.SUBTEXT, font=self.f_xs).pack(side="right")

        if self._panel_focus_idx is None:
            self._panel_focus_idx = 0
        else:
            self._panel_focus_idx = max(0, min(self._panel_focus_idx, len(self._panel_items) - 1))
        self._update_day_panel_highlights()
        self._position_day_panel()
        panel.after_idle(self._position_day_panel)

    def _delete_calendar_row(self, target):
        records = self.account.transactions
        if target not in records:
            return
        if not self._undo_jobs:
            self._undo_order = records.copy()
        else:
            known = set(self._undo_order)
            self._undo_order.extend(t for t in records if t not in known)
        self.account.delete_transaction(target)
        self._undo_jobs[target] = self.root.after(8000, self._expire_calendar_undo, target)
        self._refresh_all()

    def _expire_calendar_undo(self, target):
        self._undo_jobs.pop(target, None)
        if not self._undo_jobs:
            self._undo_order.clear()
        self._refresh_day_panel()

    def _undo_calendar_row(self, target):
        job = self._undo_jobs.pop(target, None)
        if job is None:
            return
        self.root.after_cancel(job)
        records = self.account.transactions
        following = set(self._undo_order[self._undo_order.index(target) + 1:])
        pos = next((i for i, t in enumerate(records) if t in following), len(records))
        records.insert(pos, target)
        self.account.is_dirty = True
        self.account.save_data()
        if not self._undo_jobs:
            self._undo_order.clear()
        self._refresh_all()

    def _render_calendar(self):
        if self.show_all_months:
            self.cal_grid_frame.pack_forget()
            self.cal_notice_frame.pack(fill="both", expand=True)
            self.cal_title_lbl.configure(text="月曆檢視")
            self._cal_rendered_month = ""
            self._cal_cells.clear()
            self._refresh_day_panel()
            return

        self.cal_notice_frame.pack_forget()
        self.cal_grid_frame.pack(fill="both", expand=True, padx=10)
        y, m = map(int, self.current_month.split("-"))
        self.cal_title_lbl.configure(text=f"{y} 年 {m} 月")
        self._cal_rendered_month = self.current_month
        self._cal_daily = self.account.get_daily_transactions(self.current_month)
        self._refresh_day_panel()
        self._on_cal_resize()

    def _paint_calendar(self):
        self._cal_resize_job = None
        if self.active_tab != "calendar" or self.show_all_months:
            return
        c = self.cal_grid_frame
        width, height = c.winfo_width(), c.winfo_height()
        if min(width, height) < 10:
            return
        y, m = map(int, self.current_month.split("-"))
        weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(y, m)
        col_w = width / 7
        header = max(36, self.font_cal_amt_lg.metrics("linespace") * 2)
        row_h = (height - header) / len(weeks)
        day_font = self.f_cal_day_lg if row_h >= 82 else self.f_cal_day_sm
        font = self.font_cal_item_lg if row_h >= 82 else self.font_cal_item_sm
        amount_font = self.font_cal_amt_lg if row_h >= 82 else self.font_cal_amt_sm
        line = font.metrics("linespace") + 1
        top_h = line + 7
        capacity = max(0, int((row_h - top_h - 4) // line))
        selected = self.date_var.get().strip()

        c.delete("all")
        self._cal_cells.clear()
        for col, name in enumerate("日一二三四五六"):
            weekend = col in (0, 6)
            c.create_rectangle(col * col_w + 2, 0, (col + 1) * col_w - 2, header - 2,
                               fill="#F4E1DC" if weekend else "#E2EAF0", outline="")
            c.create_text((col + .5) * col_w, (header - 2) / 2, text=f"星期{name}",
                          font=self.f_cal_head, fill="#823C38" if weekend else "#263D50")
        for week, days in enumerate(weeks):
            for col, day in enumerate(days):
                if not day:
                    continue
                date = f"{self.current_month}-{day:02d}"
                tag = "day_" + date
                x, y0 = col * col_w + 2, header + week * row_h + 2
                right, bottom = (col + 1) * col_w - 2, header + (week + 1) * row_h - 2
                rows = self._cal_daily.get(day, [])
                net = sum(t.amount if t.trans_type == "收入" else -t.amount for t in rows)
                bg = self.YELLOW_SOFT if net < 0 else self.BLUE_SOFT if net > 0 else "#FFFFFF"
                item = c.create_rectangle(x, y0, right, bottom, tags=(tag,),
                                          fill=self.YELLOW_SOFT if date == selected else bg,
                                          outline="#AD8846" if date == selected else self.BORDER,
                                          width=2 if date == selected else 1)
                self._cal_cells[date] = (item, bg)
                c.create_text(x + 6, y0 + 3, text=str(day), anchor="nw", font=day_font,
                              fill=self.INK, tags=(tag,))
                if len(rows) > 1:
                    total = ("+" if net > 0 else "") + fmt_num(net)
                    if amount_font.measure(total) < col_w - 38:
                        c.create_text(right - 5, y0 + 5, text=total, anchor="ne", font=amount_font,
                                      fill=self.CAL_INC_TEXT if net > 0 else self.CAL_EXP_TEXT, tags=(tag,))
                visible = capacity if len(rows) <= capacity else max(0, capacity - 1)
                for idx, t in enumerate(rows[:visible]):
                    amount = ("+" if t.trans_type == "收入" else "-") + fmt_num(t.amount)
                    py = y0 + top_h + idx * line
                    available = right - x - 15 - amount_font.measure(amount)
                    reason = t.get_reason()
                    if font.measure(reason) > available:
                        lo, hi = 0, len(reason)
                        while lo < hi:
                            mid = (lo + hi + 1) // 2
                            if font.measure(reason[:mid] + "…") <= available:
                                lo = mid
                            else:
                                hi = mid - 1
                        reason = reason[:lo] + "…" if lo else ""
                    c.create_text(x + 5, py, text=reason, font=font, anchor="nw", fill=self.INK, tags=(tag,))
                    if amount_font.measure(amount) < right - x - 8:
                        c.create_text(right - 5, py, text=amount, font=amount_font, anchor="ne",
                                      fill=self.CAL_INC_TEXT if t.trans_type == "收入" else self.CAL_EXP_TEXT,
                                      tags=(tag,))
                if capacity and len(rows) > visible:
                    c.create_text(x + 5, y0 + top_h + visible * line, anchor="nw",
                                  text=f"另有 {len(rows) - visible} 筆", font=font, fill=self.SUBTEXT, tags=(tag,))
        self._last_selected_cal_date = selected
        if self._panel_date:
            self._position_day_panel()

    def _draw_donut_and_legend(self, cat_totals: dict[str, int | float]):
        c = self.donut_canvas
        c.delete("all")
        self._donut_img_id = None
        self._donut_render_slices = []
        self._donut_photo_cache = {}
        self._donut_active_highlight = None
        self._chart_order = []
        self._chart_legend_items = []
        self._chart_row_rects = {}

        total = normalize_number(sum(cat_totals.values()))
        self._donut_total = total
        self._donut_hit_slices = []
        cx = cy = self.DONUT_SIZE / 2.0
        kind = self.chart_type

        if total <= 0:
            self._donut_photo = render_smooth_donut_photo(
                self.DONUT_SIZE, self.DONUT_R_OUT, self.DONUT_R_IN, [(0.0, 360.0, self.NEUTRAL)]
            )
            c.create_image(0, 0, anchor="nw", image=self._donut_photo)
            c.create_text(cx, cy, text=f"尚無{kind}", font=self.f_md_b, fill=self.SUBTEXT)
            self._donut_text_ids = None
            self._paint_chart_legend()
            self.chart_legend_canvas.yview_moveto(0)
            self._update_chart_nav_styles()
            return

        sorted_items = sorted(cat_totals.items(), key=lambda x: x[1], reverse=True)
        render_slices: list[tuple[float, float, str]] = []
        cur_deg = 0.0

        for idx, (name, amt) in enumerate(sorted_items):
            cat = self.account.get_or_create_category(name)
            pct = amt / total
            next_deg = 360.0 if idx == len(sorted_items) - 1 else cur_deg + pct * 360.0
            render_slices.append((cur_deg, next_deg, cat.color))
            self._donut_hit_slices.append((cur_deg, next_deg, cat.icon, name, amt, pct * 100, cat.color))
            self._chart_order.append(name)
            self._chart_legend_items.append((name, cat.icon, cat.color, amt, pct * 100))
            cur_deg = next_deg

        self._donut_render_slices = render_slices
        self._donut_photo = render_smooth_donut_photo(
            self.DONUT_SIZE, self.DONUT_R_OUT, self.DONUT_R_IN, render_slices
        )
        self._donut_photo_cache[None] = self._donut_photo
        self._donut_img_id = c.create_image(0, 0, anchor="nw", image=self._donut_photo)

        t_top = c.create_text(cx, cy - 22, text=f"總{kind}", font=self.f_sm, fill=self.SUBTEXT)
        t_mid = c.create_text(cx, cy + 4, text=f"${fmt_num(total)}", font=self.f_donut_mid, fill=self.INK)
        t_bot = c.create_text(cx, cy + 28, text="100%", font=self.f_xs, fill=self.SUBTEXT)
        self._donut_text_ids = (t_top, t_mid, t_bot)

        if self._chart_order:
            self._chart_selected_idx = max(0, min(self._chart_selected_idx, len(self._chart_order) - 1))
        self._paint_chart_legend()
        self.chart_legend_canvas.yview_moveto(0)
        self._update_chart_nav_styles()

    def _paint_chart_legend(self):
        c = self.chart_legend_canvas
        c.delete("all")
        self._chart_row_rects = {}
        w = self._chart_legend_w or c.winfo_width()
        if w < 40:
            w = 320
        self._chart_legend_w = w
        kind = self.chart_type

        if not self._chart_legend_items:
            empty_msg = f"目前尚無{kind}紀錄" if self.show_all_months else f"本月尚無{kind}紀錄"
            c.create_text(6, 28, text=empty_msg, font=self.f_md, fill=self.SUBTEXT, anchor="nw")
            self._chart_legend_total_h = 80
            c.configure(scrollregion=(0, 0, w, 80))
            return

        c.create_text(6, 6, text=f"{kind}排行", font=self.f_md_b, fill=self.INK, anchor="nw")

        active = (
            self.active_tab == "charts"
            and self._nav_zone == "charts"
            and not self._is_text_input_focused()
        )
        selected_cat = (
            self._chart_order[self._chart_selected_idx]
            if (active and self._chart_focus_area == "list" and 0 <= self._chart_selected_idx < len(self._chart_order))
            else None
        )
        hl_bg = self.YELLOW_SOFT if kind == "支出" else self.BLUE_SOFT

        y = 36
        row_h = 52
        x0, x1 = 2, max(160, w - 8)
        bar_x0, bar_x1 = x0 + 10, x1 - 10
        bar_w = max(1, bar_x1 - bar_x0)

        for name, icon, color, amt, pct in self._chart_legend_items:
            y0, y1 = y, y + row_h
            is_sel = (name == selected_cat)
            rect_id = c.create_rectangle(
                x0, y0, x1, y1,
                fill=hl_bg if is_sel else "#FFFFFF",
                outline="#AD8846" if is_sel else "#FFFFFF",
                width=2 if is_sel else 1,
            )
            c.create_oval(x0 + 10, y0 + 11, x0 + 20, y0 + 21, fill=color, outline="")
            c.create_text(x0 + 27, y0 + 16, text=f"{icon} {name}", font=self.f_sm_b, fill=self.INK, anchor="w")
            c.create_text(
                x1 - 10, y0 + 16, text=f"${fmt_num(amt)} ({pct:.1f}%)",
                font=self.f_sm, fill=self.SUBTEXT, anchor="e",
            )
            c.create_rectangle(bar_x0, y0 + 34, bar_x1, y0 + 43, fill=self.NEUTRAL, outline="")
            fill_w = min(float(bar_w), max(4.0, bar_w * max(pct / 100.0, 0.02)))
            c.create_rectangle(bar_x0, y0 + 34, bar_x0 + fill_w, y0 + 43, fill=color, outline="")
            self._chart_row_rects[name] = (rect_id, float(y0), float(y1))
            y += row_h + 6

        self._chart_legend_total_h = y + 4
        c.configure(scrollregion=(0, 0, w, self._chart_legend_total_h))

    def _on_chart_legend_resize(self, event):
        if event.width <= 20 or event.width == self._chart_legend_w:
            return
        self._chart_legend_w = event.width
        self._paint_chart_legend()

    def _hit_test_chart_legend(self, event) -> tuple[int, str] | None:
        cy = self.chart_legend_canvas.canvasy(event.y)
        for idx, name in enumerate(self._chart_order):
            rect_info = self._chart_row_rects.get(name)
            if rect_info and rect_info[1] <= cy <= rect_info[2]:
                return (idx, name)
        return None

    def _on_chart_legend_click(self, event):
        hit = self._hit_test_chart_legend(event)
        if hit is not None:
            self._focus_charts(hit[0], "list")
        else:
            self._focus_active_tab()

    def _on_chart_legend_double_click(self, event):
        hit = self._hit_test_chart_legend(event)
        if hit is not None:
            self._drill_down_chart_category(hit[1])

    def _on_chart_legend_motion(self, event):
        hit = self._hit_test_chart_legend(event)
        desired = "hand2" if hit is not None else ""
        if self.chart_legend_canvas.cget("cursor") != desired:
            self.chart_legend_canvas.configure(cursor=desired)

    def _hit_test_donut_slice(self, x: float, y: float) -> int | None:
        if not self._donut_hit_slices:
            return None
        cx = cy = self.DONUT_SIZE / 2.0
        dx = x - cx
        dy = y - cy
        dist = math.hypot(dx, dy)
        if self.DONUT_R_IN - 2.5 <= dist <= self.DONUT_R_OUT + 10:
            angle = math.degrees(math.atan2(dx, -dy)) % 360.0
            for idx, (a0, a1, *_rest) in enumerate(self._donut_hit_slices):
                if a0 <= angle < a1 or (a1 == 360.0 and angle == 0.0):
                    return idx
        return None

    def _on_donut_hover(self, event):
        if not self._donut_hit_slices or not self._donut_text_ids:
            return
        idx = self._hit_test_donut_slice(event.x, event.y)
        self._sync_donut_with_selection(hover_idx=idx)

    def _on_donut_click(self, event):
        idx = self._hit_test_donut_slice(event.x, event.y)
        if idx is not None and idx < len(self._chart_order):
            self._focus_charts(idx, "list")
        else:
            self._focus_active_tab()

    def _on_donut_leave(self, _event=None):
        self._sync_donut_with_selection()

    def _render_budget_cards(self, cat_expenses: dict[str, int | float]):
        for w in self.budget_list_frame.winfo_children():
            w.destroy()
        self._budget_order = []
        self._budget_card_widgets = {}

        if self.show_all_months:
            self.budget_header_lbl.configure(text="每月分類預算（全部月份：依各單月檢查上限）")
            monthly_by_cat = self.account.get_category_monthly_expenses()
        else:
            self.budget_header_lbl.configure(text=f"每月分類預算（{self.current_month}）")
            monthly_by_cat = {}

        for name, cat in self.account.categories.items():
            if name == "薪資":
                continue
            budget = cat.monthly_budget
            is_editing = (self.editing_budget_cat == name)

            if self.show_all_months:
                month_map = monthly_by_cat.get(name, {})
                total_spent = normalize_number(sum(month_map.values()))
                if month_map:
                    max_month, max_spent = max(month_map.items(), key=lambda x: x[1])
                else:
                    max_month, max_spent = "", 0
                over_months = [(m, s) for m, s in sorted(month_map.items()) if budget > 0 and s > budget]
                is_over = len(over_months) > 0
                bar_spent = max_spent

                if budget > 0:
                    if is_over:
                        info = (
                            f"超支 {len(over_months)} 個月（最高 {max_month} ${fmt_num(max_spent)} / ${fmt_num(budget)}｜累計 ${fmt_num(total_spent)}）"
                        )
                    else:
                        info = f"未超支（單月最高 ${fmt_num(max_spent)} / ${fmt_num(budget)}｜累計 ${fmt_num(total_spent)}）"
                else:
                    info = f"全部累計 ${fmt_num(total_spent)}（未設上限）"
            else:
                spent = cat_expenses.get(name, 0)
                is_over = budget > 0 and spent > budget
                bar_spent = spent
                if budget > 0:
                    remain = normalize_number(budget - spent)
                    info = (
                        f"超支 ${fmt_num(abs(remain))}（${fmt_num(spent)} / ${fmt_num(budget)}）"
                        if is_over else
                        f"剩餘 ${fmt_num(remain)}（${fmt_num(spent)} / ${fmt_num(budget)}）"
                    )
                else:
                    info = f"已花費 ${fmt_num(spent)}（未設上限）"

            card_bg = self.RED_SOFT if is_over else self.TILE_BG
            card_border = "#EAD5D5" if is_over else self.BORDER
            card = self._card_box(self.budget_list_frame, bg=card_bg, border=card_border)
            card.pack(fill="x", pady=5, padx=(0, 6))
            card_idx = len(self._budget_order)
            self._budget_order.append(name)
            self._budget_card_widgets[name] = (card, card_border)

            inner = tk.Frame(card, bg=card_bg, padx=12, pady=9)
            inner.pack(fill="x")

            top = tk.Frame(inner, bg=card_bg)
            top.pack(fill="x")
            cat_lbl = tk.Label(top, text=f"{cat.icon} {name}", font=self.f_sm_b,
                               bg=card_bg, fg=self.RED_TEXT if is_over else self.INK)
            cat_lbl.pack(side="left")

            tk.Button(
                top,
                text="收合" if is_editing else "調整",
                font=self.f_xs,
                bg=self.YELLOW if is_editing else "#FFFFFF",
                fg=self.INK,
                activebackground=self.TILE_HOVER,
                bd=0,
                relief="flat",
                cursor="hand2",
                padx=12,
                pady=2,
                command=lambda n=name: self._toggle_inline_budget_editor(n),
            ).pack(side="right")

            info_lbl = tk.Label(top, text=info, font=self.f_sm, bg=card_bg,
                                fg=self.RED_TEXT if is_over else self.SUBTEXT)
            info_lbl.pack(side="right", padx=(0, 10))

            for click_w in (card, inner, top, cat_lbl, info_lbl):
                click_w.bind("<Button-1>", lambda _e, i=card_idx: self._select_budget_card(i), add="+")

            if budget > 0:
                ratio = min(bar_spent / budget, 1.0)
                track = tk.Frame(inner, bg="#FFFFFF", height=9)
                track.pack(fill="x", pady=(8, 0))
                track.pack_propagate(False)
                if ratio > 0:
                    tk.Frame(track, bg=self.RED if is_over else cat.color).place(
                        relx=0, rely=0, relwidth=ratio, relheight=1
                    )

            if is_editing:
                edit_box = self._card_box(inner, bg="#FFFFFF", border=self.BORDER)
                edit_box.pack(fill="x", pady=(8, 0))
                edit_row = tk.Frame(edit_box, bg="#FFFFFF", padx=10, pady=8)
                edit_row.pack(fill="x")

                tk.Label(edit_row, text="每月上限 $", font=self.f_xs, bg="#FFFFFF", fg=self.SUBTEXT).pack(side="left")
                self._inline_budget_var = tk.StringVar(value=str(int(round(budget))))
                self._inline_budget_var.trace_add("write", self._on_inline_budget_var_changed)
                entry = self._soft_entry(edit_row, self._inline_budget_var, self.f_sm_b, width=8, justify="right")
                self._inline_budget_entry = entry
                entry.pack(side="left", padx=(4, 8), ipady=2)
                entry.focus_set()
                entry.icursor(tk.END)
                entry.selection_range(0, tk.END)
                entry.bind("<Return>", lambda _e, n=name: self._save_inline_budget(n))
                entry.bind("<Escape>", lambda _e: (self._cancel_inline_budget_editor(), "break")[1])

                for label, delta in (("-500", -500), ("+500", 500), ("+1000", 1000)):
                    tk.Button(
                        edit_row, text=label, font=self.f_xs, bg=self.TILE_BG, fg=self.INK,
                        activebackground=self.TILE_HOVER, bd=0, relief="flat", cursor="hand2",
                        padx=8, pady=2, command=lambda d=delta: self._nudge_inline_budget(d),
                    ).pack(side="left", padx=2)

                tk.Button(
                    edit_row, text="取消", font=self.f_xs, bg=self.TILE_BG, fg=self.SUBTEXT,
                    activebackground=self.TILE_HOVER, bd=0, relief="flat", cursor="hand2",
                    padx=10, pady=2, command=lambda n=name: self._toggle_inline_budget_editor(n),
                ).pack(side="right", padx=(6, 0))

                tk.Button(
                    edit_row, text="儲存", font=self.f_xs, bg=self.GREEN, fg=self.INK,
                    activebackground="#A9C5B0", bd=0, relief="flat", cursor="hand2",
                    padx=12, pady=2, command=lambda n=name: self._save_inline_budget(n),
                ).pack(side="right")

        self.budget_list_frame.update_idletasks()
        self.budget_canvas.configure(scrollregion=self.budget_canvas.bbox("all"))
        if self._budget_order:
            self._budget_selected_idx = max(0, min(self._budget_selected_idx, len(self._budget_order) - 1))
        self._update_budget_card_styles()


if __name__ == "__main__":
    root = tk.Tk()
    app = SimpleAccountingApp(root)
    root.mainloop()
