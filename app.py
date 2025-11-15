from datetime import date, datetime, timedelta
import os

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
)
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    Date,
    select,
    delete,
)
from sqlalchemy.orm import sessionmaker, declarative_base

# -------------------------------------------------
# Flask & DB 初期化
# -------------------------------------------------

app = Flask(__name__)

# セッションや flash に必要
app.config["SECRET_KEY"] = "replace-this-with-a-better-secret-key"

# Render / Neon 用の DATABASE_URL があればそれを使う。なければローカル SQLite。
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    # ローカル開発用 SQLite
    os.makedirs("data", exist_ok=True)
    DATABASE_URL = "sqlite:///data/app.db"
else:
    # 一部の環境では postgres:// という古い書式になっていることがあるので修正
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


# -------------------------------------------------
# ヘルパー
# -------------------------------------------------

def to_date(s: str) -> date:
    """'YYYY-MM-DD' の文字列を date 型に変換"""
    return datetime.strptime(s, "%Y-%m-%d").date()


# -------------------------------------------------
# モデル定義
# -------------------------------------------------


class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True)

    # インデックス名（1行目に出す名前）
    # 例）「体幹＋姿勢リセット」「上半身ベーシック」
    title = Column(String(100), nullable=False)

    # このプランに含まれる種目（カンマ区切り）
    # 例）"プランク,ドローイン,背伸びストレッチ"
    exercises = Column(Text, nullable=True)

    planned_date = Column(Date, nullable=False)
    planned_minutes = Column(Integer, nullable=False, default=30)
    notes = Column(Text, nullable=True)


class Log(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True)

    # どの Plan に紐づくか（なくてもOK）
    plan_id = Column(Integer, nullable=True)

    # 個々の種目ログの場合：種目名（Plan.exercises の1つ）
    exercise_name = Column(String(100), nullable=True)

    actual_date = Column(Date, nullable=False)

    # 時間系
    minutes = Column(Integer, nullable=False, default=0)
    seconds_total = Column(Integer, nullable=False, default=0)
    duration_str = Column(String(8), nullable=False, default="00:00:00")

    # 回数ログ
    reps = Column(Integer, nullable=True, default=None)
    sets = Column(Integer, nullable=True, default=None)

    notes = Column(Text, nullable=True)


Base.metadata.create_all(engine)


# -------------------------------------------------
# 共通：ユーザーレベル（1/2/3）
# -------------------------------------------------


def get_user_level() -> int:
    """アプリ全体のトレーニングレベル（1:初心者, 2:中級, 3:上級）"""
    lvl = session.get("user_level", 1)
    try:
        lvl = int(lvl)
    except Exception:
        lvl = 1
    if lvl < 1:
        lvl = 1
    if lvl > 3:
        lvl = 3
    return lvl


def recommended_reps_for_exercise(exercise_name: str, level: int) -> int:
    """
    種目とレベルから「目安回数」を決める。
    今はシンプルに：レベル1=10回, 2=20回, 3=30回。
    将来、種目ごとに変えるのも簡単に拡張できる。
    """
    base = {1: 10, 2: 20, 3: 30}.get(level, 10)
    return base


# -------------------------------------------------
# ホーム画面
# -------------------------------------------------


@app.route("/")
def index():
    """ホーム：今日以降の計画 / 未消化の過去計画 + 全体進捗バー"""
    today = date.today()
    with SessionLocal() as db:
        upcoming = (
            db.execute(
                select(Plan)
                .where(Plan.planned_date >= today)
                .order_by(Plan.planned_date.asc(), Plan.id.asc())
            )
            .scalars()
            .all()
        )

        overdue = (
            db.execute(
                select(Plan)
                .where(Plan.planned_date < today)
                .order_by(Plan.planned_date.asc(), Plan.id.asc())
            )
            .scalars()
            .all()
        )

        # 全体進捗：計画のある日数 vs 実施がある日数
        all_plans = db.execute(select(Plan)).scalars().all()
        all_logs = db.execute(select(Log)).scalars().all()

        plan_dates = {p.planned_date for p in all_plans}
        log_dates = {l.actual_date for l in all_logs}
        done_dates = plan_dates & log_dates

        total_days = len(plan_dates)
        done_days = len(done_dates)
        if total_days > 0:
            overall_percent = int(done_days / total_days * 100)
        else:
            overall_percent = 0

        if overall_percent >= 70:
            overall_color = "success"
        elif overall_percent >= 50:
            overall_color = "warning"
        else:
            overall_color = "danger"

    return render_template(
        "index.html",
        upcoming=upcoming,
        overdue=overdue,
        overall_percent=overall_percent,
        overall_color=overall_color,
        total_days=total_days,
        done_days=done_days,
    )


# -------------------------------------------------
# 設定（レベル）
# -------------------------------------------------


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        level_str = request.form.get("level", "1")
        try:
            level = int(level_str)
        except Exception:
            level = 1
        if level < 1:
            level = 1
        if level > 3:
            level = 3
        session["user_level"] = level
        flash("トレーニングレベルを保存しました。", "success")
        return redirect(url_for("index"))

    current_level = get_user_level()
    return render_template("settings.html", current_level=current_level)


# -------------------------------------------------
# 計画の追加 / 編集 / 延期 / 削除
# -------------------------------------------------


@app.route("/plan/new", methods=["GET", "POST"])
def plan_new():
    if request.method == "POST":
        try:
            title = request.form.get("title") or ""
            planned_date = to_date(request.form.get("planned_date"))
            planned_minutes = int(request.form.get("planned_minutes") or 0)
            notes = request.form.get("notes") or None

            # チェックボックスで選択された種目
            exercises_selected = request.form.getlist("exercises")
            exercises_selected = [e.strip() for e in exercises_selected if e.strip()]
            exercises_str = ",".join(exercises_selected) if exercises_selected else None

            p = Plan(
                title=title,
                planned_date=planned_date,
                planned_minutes=planned_minutes,
                notes=notes,
                exercises=exercises_str,
            )
            with SessionLocal() as db:
                db.add(p)
                db.commit()

            flash("計画を追加しました。", "success")
            return redirect(url_for("index"))
        except Exception as e:
            flash(f"エラー: {e}", "danger")

    default_date = request.args.get("date") or date.today().isoformat()
    return render_template("plan_new.html", today=default_date)


@app.route("/plan/<int:plan_id>/edit", methods=["GET", "POST"])
def plan_edit(plan_id):
    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        if not plan:
            flash("計画が見つかりません。", "warning")
            return redirect(url_for("index"))

        if request.method == "POST":
            try:
                plan.title = request.form.get("title") or ""
                plan.planned_date = to_date(request.form.get("planned_date"))
                plan.planned_minutes = int(request.form.get("planned_minutes") or 0)
                plan.notes = request.form.get("notes") or None

                exercises_selected = request.form.getlist("exercises")
                exercises_selected = [e.strip() for e in exercises_selected if e.strip()]
                plan.exercises = (
                    ",".join(exercises_selected) if exercises_selected else None
                )

                db.commit()
                flash("計画を更新しました。", "success")
                return redirect(url_for("plan_detail", plan_id=plan_id))
            except Exception as e:
                flash(f"エラー: {e}", "danger")

        return render_template("plan_edit.html", plan=plan)


@app.route("/plan/<int:plan_id>/postpone", methods=["POST"])
def plan_postpone(plan_id):
    """計画日の延期"""
    with SessionLocal() as db:
        p = db.get(Plan, plan_id)
        if not p:
            flash("計画が見つかりません。", "warning")
            return redirect(url_for("index"))

        new_date_str = request.form.get("new_date")
        days_str = request.form.get("days")

        try:
            if new_date_str:
                p.planned_date = to_date(new_date_str)
            elif days_str:
                d = int(days_str)
                p.planned_date = p.planned_date + timedelta(days=d)
            else:
                flash("延期の指定が不正です。", "warning")
                return redirect(url_for("index"))

            db.commit()
            flash("計画日を変更しました。", "success")
        except Exception as e:
            flash(f"エラー: {e}", "danger")

    return redirect(url_for("index"))


@app.route("/plan/<int:plan_id>/delete", methods=["POST"])
def plan_delete(plan_id):
    """計画の削除（関連ログも削除）"""
    with SessionLocal() as db:
        p = db.get(Plan, plan_id)
        if not p:
            flash("計画が見つかりません。", "warning")
            return redirect(url_for("index"))

        db.execute(delete(Log).where(Log.plan_id == plan_id))
        db.delete(p)
        db.commit()

    flash("計画と関連する記録を削除しました。", "info")
    return redirect(url_for("index"))


# -------------------------------------------------
# 日別ページ
# -------------------------------------------------


@app.route("/day/<date_str>")
def day_view(date_str):
    d = to_date(date_str)
    with SessionLocal() as db:
        plans = (
            db.execute(
                select(Plan)
                .where(Plan.planned_date == d)
                .order_by(Plan.id.asc())
            )
            .scalars()
            .all()
        )

        logs = (
            db.execute(
                select(Log)
                .where(Log.actual_date == d)
                .order_by(Log.id.asc())
            )
            .scalars()
            .all()
        )

    done_map = {l.plan_id for l in logs if l.plan_id is not None}
    total_plans = len(plans)
    done_plans = len([p for p in plans if p.id in done_map])

    if total_plans > 0:
        date_progress_percent = int(done_plans / total_plans * 100)
    else:
        date_progress_percent = 0

    if date_progress_percent >= 70:
        date_progress_color = "success"
    elif date_progress_percent >= 50:
        date_progress_color = "warning"
    else:
        date_progress_color = "danger"

    return render_template(
        "day.html",
        date=d,
        plans=plans,
        logs=logs,
        done_map=done_map,
        date_progress_percent=date_progress_percent,
        date_progress_color=date_progress_color,
        done_plans=done_plans,
        total_plans=total_plans,
    )


# -------------------------------------------------
# 自動 6か月180日プラン生成
# -------------------------------------------------


def build_auto_plan_entry(day_index: int, d: date) -> Plan:
    """
    6か月180日 用の自動プラン 1日分を返す。
    day_index: 0〜179
    d: 日付
    """
    week = day_index // 7
    if week < 4:
        phase = "intro"  # 導入期
    elif week < 12:
        phase = "base"   # 基礎期
    else:
        phase = "strong" # 強化期

    title = ""
    notes = ""
    minutes = 20
    exercises = None

    # 導入期：3日に1回 アクティブ休養
    if phase == "intro":
        is_rest = (day_index % 3 == 2)
        if is_rest:
            title = "アクティブ休養（導入期）"
            notes = "ストレッチ＋深呼吸で回復日。ウォーキングは軽め。"
            exercises = "ストレッチ,ウォーキング"
            minutes = 20
            return Plan(
                title=title,
                planned_date=d,
                planned_minutes=minutes,
                notes=notes,
                exercises=exercises,
            )
        pattern = day_index % 3
        if pattern == 0:
            title = "体幹＋姿勢リセット"
            notes = "プランク・ドローイン・背伸びストレッチで体幹を起こす導入期。"
            exercises = "プランク,ドローイン,背伸びストレッチ"
            minutes = 20
        elif pattern == 1:
            title = "ウォーキング（導入期）"
            notes = "1kmウォーク＋脚ストレッチ。ラン前の土台作り。"
            exercises = "ウォーキング,脚ストレッチ"
            minutes = 20
        else:
            title = "体幹＋ウォークMIX"
            notes = "軽い体幹＋短めウォークで全身を慣らす。"
            exercises = "プランク,ウォーキング"
            minutes = 25

    # 基礎期：週1回アクティブ休養（日曜）
    elif phase == "base":
        is_rest = (d.weekday() == 6)
        if is_rest:
            title = "アクティブ休養（基礎期）"
            notes = "ウォーキング＋ヨガ風ストレッチ。心肺と筋肉の回復日。"
            exercises = "ウォーキング,ストレッチ"
            minutes = 25
            return Plan(
                title=title,
                planned_date=d,
                planned_minutes=minutes,
                notes=notes,
                exercises=exercises,
            )
        pattern = day_index % 4
        if pattern == 0:
            title = "上半身ベーシック"
            notes = "腕立て・軽い懸垂・肩周りストレッチで上半身の土台づくり。"
            exercises = "腕立て伏せ,懸垂,背伸びストレッチ"
            minutes = 25
        elif pattern == 1:
            title = "下半身ベーシック"
            notes = "スクワット・ランジ・カーフレイズで下半身を鍛える。"
            exercises = "スクワット,ランジ,カーフレイズ"
            minutes = 25
        elif pattern == 2:
            title = "体幹ベーシック"
            notes = "フロントプランク・ドローインで体幹安定性UP。"
            exercises = "プランク,ドローイン"
            minutes = 20
        else:
            title = "有酸素ラン（基礎）"
            notes = "1kmラン＋ウォーク。心肺機能をじわじわ上げる。"
            exercises = "ランニング,ウォーキング"
            minutes = 25

    # 強化期：週1回アクティブ休養（日曜）
    else:
        is_rest = (d.weekday() == 6)
        if is_rest:
            title = "アクティブ休養（強化期）"
            notes = "疲れに応じてウォーク・ストレッチ中心で調整。"
            exercises = "ウォーキング,ストレッチ"
            minutes = 25
            return Plan(
                title=title,
                planned_date=d,
                planned_minutes=minutes,
                notes=notes,
                exercises=exercises,
            )
        pattern = day_index % 4
        if pattern == 0:
            title = "上半身強化（懸垂中心）"
            notes = "懸垂・腕立ての回数UP。上半身ムキムキ化のメイン日。"
            exercises = "懸垂,腕立て伏せ,背伸びストレッチ"
            minutes = 30
        elif pattern == 1:
            title = "下半身強化（ラン＋筋トレ）"
            notes = "スクワット＋短めラン。脚力と心肺をまとめて鍛える。"
            exercises = "スクワット,ランニング,カーフレイズ"
            minutes = 30
        elif pattern == 2:
            title = "体幹維持（強化期）"
            notes = "強度を少し上げたプランク系で体幹を維持・強化。"
            exercises = "プランク,ドローイン"
            minutes = 20
        else:
            title = "ラン強化（ペース走）"
            notes = "1kmペース走＋少し速めの区間。"
            exercises = "ランニング,ウォーキング"
            minutes = 25

    return Plan(
        title=title,
        planned_date=d,
        planned_minutes=minutes,
        notes=notes,
        exercises=exercises,
    )


@app.route("/auto_plan", methods=["GET", "POST"])
def auto_plan():
    if request.method == "POST":
        try:
            start_str = request.form.get("start_date")
            start_date = to_date(start_str)
        except Exception:
            flash("開始日が正しくありません。", "danger")
            return redirect(url_for("auto_plan"))

        end_date = start_date + timedelta(days=179)

        with SessionLocal() as db:
            # 対象期間の既存プランを削除
            db.execute(
                delete(Plan).where(
                    Plan.planned_date >= start_date,
                    Plan.planned_date <= end_date,
                )
            )

            # 180日分を作成
            count = 0
            for i in range(180):
                d = start_date + timedelta(days=i)
                p = build_auto_plan_entry(i, d)
                db.add(p)
                count += 1
            db.commit()

        flash(
            f"{start_date} から {end_date} までの {count} 日分のプランを自動生成しました。",
            "success",
        )
        return redirect(url_for("index"))

    today_str = date.today().isoformat()
    return render_template("auto_plan.html", today=today_str)


# -------------------------------------------------
# Plan 詳細ページ（インデックス＋種目リンク）
# -------------------------------------------------


@app.route("/plan/<int:plan_id>", methods=["GET", "POST"])
def plan_detail(plan_id):
    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        if not plan:
            flash("計画が見つかりません。", "warning")
            return redirect(url_for("index"))

        logs = (
            db.execute(
                select(Log)
                .where(Log.plan_id == plan_id, Log.exercise_name.is_(None))
                .order_by(Log.actual_date.asc(), Log.id.asc())
            )
            .scalars()
            .all()
        )

        # 種目リスト
        exercises_list = []
        if plan.exercises:
            for raw in plan.exercises.split(","):
                name = raw.strip()
                if name:
                    exercises_list.append(name)

        # 合計秒
        total_seconds = sum(l.seconds_total for l in logs)
        h = total_seconds // 3600
        m = (total_seconds % 3600) // 60
        s = total_seconds % 60
        total_str = f"{h:02d}:{m:02d}:{s:02d}"
        done_minutes = total_seconds // 60

        # 予定時間に対する進捗
        target_seconds = (plan.planned_minutes or 0) * 60
        if target_seconds > 0:
            ratio = total_seconds / target_seconds
            plan_progress_percent = int(ratio * 100)
        else:
            plan_progress_percent = 0
        plan_progress_width = min(plan_progress_percent, 100)
        if plan_progress_percent >= 70:
            plan_progress_color = "success"
        elif plan_progress_percent >= 50:
            plan_progress_color = "warning"
        else:
            plan_progress_color = "danger"

        if request.method == "POST":
            try:
                seconds_total = int(request.form.get("seconds_total") or 0)
                if seconds_total <= 0:
                    flash("計測時間が0秒です。Start/Stopで時間を計測してください。", "warning")
                    return redirect(url_for("plan_detail", plan_id=plan_id))

                actual_date_str = request.form.get("actual_date") or date.today().isoformat()
                actual_date_val = to_date(actual_date_str)

                hh = seconds_total // 3600
                mm = (seconds_total % 3600) // 60
                ss = seconds_total % 60
                duration_str = f"{hh:02d}:{mm:02d}:{ss:02d}"

                new_log = Log(
                    plan_id=plan_id,
                    exercise_name=None,  # プラン全体ログ
                    actual_date=actual_date_val,
                    minutes=seconds_total // 60,
                    seconds_total=seconds_total,
                    duration_str=duration_str,
                    notes=request.form.get("notes") or None,
                )
                db.add(new_log)
                db.commit()
                flash("プラン全体の時間を追加しました。", "success")
                return redirect(url_for("plan_detail", plan_id=plan_id))
            except Exception as e:
                flash(f"エラー: {e}", "danger")
                return redirect(url_for("plan_detail", plan_id=plan_id))

    return render_template(
        "plan_detail.html",
        plan=plan,
        logs=logs,
        exercises_list=exercises_list,
        total_str=total_str,
        today=date.today().isoformat(),
        plan_progress_percent=plan_progress_percent,
        plan_progress_width=plan_progress_width,
        plan_progress_color=plan_progress_color,
        done_minutes=done_minutes,
    )


# -------------------------------------------------
# 種目専用ページ（クリックして開く）
# -------------------------------------------------


@app.route("/plan/<int:plan_id>/exercise/<int:ex_index>", methods=["GET", "POST"])
def exercise_detail(plan_id, ex_index):
    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        if not plan:
            flash("計画が見つかりません。", "warning")
            return redirect(url_for("index"))

        # 種目リストを再構成
        raw_list = (plan.exercises or "").split(",")
        exercises_list = [x.strip() for x in raw_list if x.strip()]

        if ex_index < 0 or ex_index >= len(exercises_list):
            flash("種目が見つかりません。", "warning")
            return redirect(url_for("plan_detail", plan_id=plan_id))

        ex_name = exercises_list[ex_index]

        if request.method == "POST":
            try:
                seconds_total = int(request.form.get("seconds_total") or 0)
                reps = request.form.get("reps")
                sets = request.form.get("sets")
                reps_val = int(reps) if reps not in (None, "") else None
                sets_val = int(sets) if sets not in (None, "") else None

                actual_date_str = request.form.get("actual_date") or date.today().isoformat()
                actual_date_val = to_date(actual_date_str)

                hh = seconds_total // 3600
                mm = (seconds_total % 3600) // 60
                ss = seconds_total % 60
                duration_str = f"{hh:02d}:{mm:02d}:{ss:02d}"

                new_log = Log(
                    plan_id=plan_id,
                    exercise_name=ex_name,
                    actual_date=actual_date_val,
                    minutes=seconds_total // 60,
                    seconds_total=seconds_total,
                    duration_str=duration_str,
                    reps=reps_val,
                    sets=sets_val,
                    notes=request.form.get("notes") or None,
                )
                db.add(new_log)
                db.commit()
                flash("種目の記録を追加しました。", "success")
                return redirect(url_for("exercise_detail", plan_id=plan_id, ex_index=ex_index))
            except Exception as e:
                flash(f"エラー: {e}", "danger")
                return redirect(url_for("exercise_detail", plan_id=plan_id, ex_index=ex_index))

        # この種目のログ一覧
        logs = (
            db.execute(
                select(Log)
                .where(Log.plan_id == plan_id, Log.exercise_name == ex_name)
                .order_by(Log.actual_date.asc(), Log.id.asc())
            )
            .scalars()
            .all()
        )

        total_seconds = sum(l.seconds_total for l in logs)
        th = total_seconds // 3600
        tm = (total_seconds % 3600) // 60
        ts = total_seconds % 60
        total_str = f"{th:02d}:{tm:02d}:{ts:02d}"

        total_reps = sum(l.reps or 0 for l in logs)
        total_sets = sum(l.sets or 0 for l in logs)

    level = get_user_level()
    recommended = recommended_reps_for_exercise(ex_name, level)

    return render_template(
        "exercise_detail.html",
        plan=plan,
        ex_name=ex_name,
        exercise_name=ex_name,  # ★ 追加：テンプレート用の種目名
        ex_index=ex_index,
        logs=logs,
        total_str=total_str,
        total_reps=total_reps,
        total_sets=total_sets,
        today=date.today().isoformat(),
        level=level,
        recommended=recommended,
    )


# -------------------------------------------------
# 汎用ログ（一覧・編集・削除）
# -------------------------------------------------


@app.route("/logs")
def logs():
    with SessionLocal() as db:
        rows = (
            db.execute(
                select(Log).order_by(Log.actual_date.desc(), Log.id.desc())
            )
            .scalars()
            .all()
        )
    return render_template("logs.html", rows=rows)


@app.route("/log/<int:log_id>/edit", methods=["GET", "POST"])
def log_edit(log_id):
    with SessionLocal() as db:
        l = db.get(Log, log_id)
        if not l:
            flash("記録が見つかりません。", "warning")
            return redirect(url_for("logs"))

        if request.method == "POST":
            try:
                l.actual_date = to_date(request.form.get("actual_date"))

                seconds_total = int(request.form.get("seconds_total") or 0)
                l.seconds_total = seconds_total
                l.minutes = seconds_total // 60
                hh = seconds_total // 3600
                mm = (seconds_total % 3600) // 60
                ss = seconds_total % 60
                l.duration_str = f"{hh:02d}:{mm:02d}:{ss:02d}"

                reps = request.form.get("reps")
                sets = request.form.get("sets")
                l.reps = int(reps) if reps not in (None, "") else None
                l.sets = int(sets) if sets not in (None, "") else None

                l.notes = request.form.get("notes") or None

                db.commit()
                flash("実施記録を修正しました。", "success")
                return redirect(url_for("logs"))
            except Exception as e:
                flash(f"エラー: {e}", "danger")
                return redirect(url_for("log_edit", log_id=log_id))

    return render_template("log_edit.html", log=l)


@app.route("/log/<int:log_id>/delete", methods=["POST"])
def log_delete(log_id):
    with SessionLocal() as db:
        l = db.get(Log, log_id)
        if not l:
            flash("記録が見つかりません。", "warning")
            return redirect(url_for("logs"))
        db.delete(l)
        db.commit()

    flash("実施記録を削除しました。", "info")
    return redirect(url_for("logs"))


# -------------------------------------------------
# メイン
# -------------------------------------------------


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
