import os
import time
import threading
import requests
import json
from datetime import datetime, timezone
from telebot import TeleBot, types
from dotenv import load_dotenv
from web3 import Web3
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderType, MarketOrderArgs
from py_clob_client.order_builder.constants import BUY
from py_clob_client.constants import POLYGON

def validate_environment():
    """التحقق من جميع المتغيرات المطلوبة قبل التشغيل"""
    required = {
        "TELEGRAM_TOKEN": os.getenv("TELEGRAM_TOKEN"),
        "PRIVATE_KEY": os.getenv("PRIVATE_KEY"),
        "FUNDER_ADDRESS": os.getenv("FUNDER_ADDRESS"),
        "API_KEY": os.getenv("API_KEY"),
        "API_SECRET": os.getenv("API_SECRET"),
        "API_PASSPHRASE": os.getenv("API_PASSPHRASE"),
    }
    
    missing = [k for k, v in required.items() if not v or not v.strip()]
    
    if missing:
        print("\n" + "🔴" * 50)
        print("❌ لا يمكن بدء البوت: متغيرات البيئة التالية مفقودة:")
        for var in missing:
            print(f"   • {var}")
        print("\n📋 لإصلاح المشكلة:")
        print("   1. افتح لوحة تحكم Railway")
        print("   2. اذهب إلى: مشروعك → Variables")
        print("   3. أضف المتغيرات المفقودة بالقيم الصحيحة")
        print("   4. أعد تشغيل التطبيق (Redeploy)")
        print("🔴" * 50 + "\n")
        return False
    
    print("✅ جميع متغيرات البيئة مضبوطة بشكل صحيح!")
    return True

# 🎯 استدعِ الدالة قبل أي كود آخر
if __name__ == "__main__":
    load_dotenv()
    
    if not validate_environment():
        exit(1)  # توقف هنا إذا كانت المتغيرات ناقصة
    
    # ... بقية الكود الأصلي ...


# تحميل المتغيرات من ملف .env
load_dotenv()

# ============================================
# 1. الإعدادات الأساسية (Blockchain + CLOB)
# ============================================
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDC_ABI = '[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},{"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"}]'

RPC_LIST = [
    os.getenv("POLYGON_RPC"),
    "https://polygon-rpc.com",
    "https://polygon.drpc.org",
]

def connect_web3():
    """محاولة الاتصال بأحد RPC المتاحة"""
    for rpc in RPC_LIST:
        if not rpc:
            continue
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 15}))
            if w3.is_connected():
                print(f"✅ Web3 Connected: {rpc[:40]}...")
                return w3
        except Exception:
            continue
    return None

w3 = connect_web3()

CLOB_HOST = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

# ✅ إنشاء كلاس بسيط بدلاً من ApiCreds المفقود
class ApiCreds:
    def __init__(self, api_key, api_secret, api_passphrase):
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase

api_creds = ApiCreds(
    api_key=os.getenv("API_KEY"),
    api_secret=os.getenv("API_SECRET"),
    api_passphrase=os.getenv("API_PASSPHRASE")
)

# إنشاء عميل Polymarket CLOB باستخدام ApiCreds المخصص
clob_client = ClobClient(
    host=CLOB_HOST,
    chain_id=POLYGON,
    key=os.getenv("PRIVATE_KEY"),          # المفتاح الخاص للمحفظة
    creds=api_creds,                        # ✅ تمرير الكائن بدلاً من القاموس
    signature_type=2,
    funder=os.getenv("FUNDER_ADDRESS"),
)

# ============================================
# 2. إعدادات البوت والصلاحيات
# ============================================
# ✅ الكود الجديد مع التحقق من المتغيرات
TOKEN = os.getenv("TELEGRAM_TOKEN")
WALLET = os.getenv("FUNDER_ADDRESS")
ALLOWED_CHAT_ID = int(os.getenv("ALLOWED_CHAT_ID", "0"))

# 🛡️ التحقق من وجود TOKEN قبل إنشاء البوت
if not TOKEN or len(TOKEN.strip()) < 10:
    print("❌ خطأ فادح: TELEGRAM_TOKEN غير مضبوط أو غير صالح!")
    print("📝 يرجى إضافة المتغير في بيئة التشغيل:")
    print("   TELEGRAM_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz")
    exit(1)  # إيقاف البرنامج فوراً لمنع الخطأ

# ✅ الآن آمن لإنشاء البوت
bot = TeleBot(TOKEN.strip())  # .strip() لإزالة المسافات الزائدة

def is_authorized(message):
    """التحقق من أن المستخدم مصرح له باستخدام البوت"""
    if ALLOWED_CHAT_ID == 0:
        return True   # إذا لم يحدد، يسمح للجميع (غير آمن)
    return message.chat.id == ALLOWED_CHAT_ID

# ============================================
# 3. إعدادات التداول (قابلة للتعديل)
# ============================================
settings = {
    "trade_amount": 1.0,
    "multiplier": 2.0,
    "max_multiplications": 3,
    "take_profit": 10.0,
    "stop_loss": 10.0,
}

state = {
    "active": False,
    "current_amount": 1.0,
    "loss_streak": 0,
    "total_pnl": 0.0,
    "chat_id": None,
}

waiting_for = {}  # لتخزين من ينتظر إدخال قيمة

# ============================================
# 4. وظائف Polymarket (جلب السوق)
# ============================================
def get_current_15m_slug():
    """توليد slug لسوق BTC 15 دقيقة الحالي"""
    now_ts = int(time.time())
    window_ts = now_ts - (now_ts % 900)   # بداية الربع ساعة الحالي
    return f"btc-updown-15m-{window_ts}", window_ts

def find_market(slug):
    """البحث عن سوق بواسطة slug"""
    try:
        url = f"{GAMMA_API}/events?slug={slug}"
        r = requests.get(url, timeout=10)
        data = r.json()
        if not data:
            return None
        event = data[0]
        markets = event.get("markets", [])
        # البحث عن سوق "up"
        for m in markets:
            if "up" in m.get("question", "").lower():
                return m
        return markets[0] if markets else None
    except Exception as e:
        print(f"Market fetch error: {e}")
        return None

def get_token_id_for_up(market):
    """استخراج token_id لسوق UP"""
    try:
        tokens = market.get("clobTokenIds") or market.get("clob_token_ids", [])
        if isinstance(tokens, str):
            tokens = json.loads(tokens)
        return str(tokens[0]) if tokens else None
    except Exception:
        return None

# ============================================
# 5. وظيفة الرصيد
# ============================================
def get_balance():
    """جلب رصيد USDC للمحفظة"""
    global w3
    if not WALLET:
        return "FUNDER_ADDRESS غير موجود"
    for attempt in range(3):
        try:
            if not w3 or not w3.is_connected():
                w3 = connect_web3()
            contract = w3.eth.contract(
                address=w3.to_checksum_address(USDC_ADDRESS),
                abi=USDC_ABI
            )
            bal = contract.functions.balanceOf(
                w3.to_checksum_address(WALLET)
            ).call()
            return bal / 10**6   # USDC له 6 أرقام عشرية
        except Exception:
            time.sleep(2)
    return "Network Busy"

# ============================================
# 6. وظائف التداول
# ============================================
def place_up_order(amount, token_id):
    """وضع أمر شراء UP"""
    try:
        order = clob_client.create_market_order(
            MarketOrderArgs(token_id=token_id, amount=amount, side=BUY)
        )
        return clob_client.post_order(order, OrderType.FOK)
    except Exception as e:
        print(f"Order error: {e}")
        return None

def seconds_until_1min_after_start():
    """عدد الثواني حتى دقيقة واحدة بعد بداية الربع ساعة"""
    now = int(time.time())
    window_start = now - (now % 900)
    target = window_start + 60
    wait = target - now
    if wait < 0:
        next_window = window_start + 900
        wait = (next_window + 60) - now
    return wait

def seconds_until_next_15m():
    """عدد الثواني حتى نهاية الربع ساعة الحالي"""
    now = int(time.time())
    return 900 - (now % 900)

def trading_loop(chat_id):
    """الحلقة الرئيسية للتداول (تعمل في خيط منفصل)"""
    bot.send_message(chat_id, "🤖 *محرك التداول نشط*\nينتظر الربع ساعة القادم...", parse_mode="Markdown")

    while state["active"]:
        try:
            wait_secs = seconds_until_1min_after_start()

            if wait_secs > 5:
                bot.send_message(
                    chat_id,
                    f"⏳ انتظار *{wait_secs // 60}د {wait_secs % 60}ث* لفتح الصفقة التالية",
                    parse_mode="Markdown"
                )
                # انتظار مع إمكانية الإيقاف
                for _ in range(wait_secs):
                    if not state["active"]:
                        return
                    time.sleep(1)

            if not state["active"]:
                return

            # --- وقت فتح الصفقة ---
            slug, window_ts = get_current_15m_slug()
            window_time = datetime.fromtimestamp(window_ts, tz=timezone.utc).strftime("%H:%M UTC")

            bot.send_message(chat_id, f"🔍 جاري البحث عن السوق...\n`{slug}`", parse_mode="Markdown")

            market = find_market(slug)
            if not market:
                bot.send_message(chat_id, f"⚠️ لم يُوجد سوق\nسيحاول في الربع ساعة القادم")
                time.sleep(60)
                continue

            token_id = get_token_id_for_up(market)
            if not token_id:
                bot.send_message(chat_id, "⚠️ لم يُوجد token_id")
                time.sleep(60)
                continue

            amount = state["current_amount"]

            # فحص حدود الربح/الخسارة
            if state["total_pnl"] <= -settings["stop_loss"]:
                bot.send_message(chat_id, f"🛑 *وصل حد الخسارة الإجمالية!*\n`{state['total_pnl']:.2f} USDC`\nتم إيقاف البوت.", parse_mode="Markdown")
                state["active"] = False
                return

            if state["total_pnl"] >= settings["take_profit"]:
                bot.send_message(chat_id, f"🎯 *وصل هدف الربح الإجمالي!*\n`{state['total_pnl']:.2f} USDC`\nتم إيقاف البوت.", parse_mode="Markdown")
                state["active"] = False
                return

            # إرسال إشعار بالصفقة
            bot.send_message(
                chat_id,
                f"🚀 *فتح صفقة UP*\n"
                f"السوق: `{window_time}`\n"
                f"المبلغ: `{amount:.2f} USDC`\n"
                f"سلسلة الخسائر: `{state['loss_streak']}`",
                parse_mode="Markdown"
            )

            # تنفيذ الأمر
            resp = place_up_order(amount, token_id)

            if resp:
                bot.send_message(chat_id, f"✅ *تم وضع الصفقة بنجاح*", parse_mode="Markdown")
            else:
                bot.send_message(chat_id, "⚠️ فشل وضع الصفقة، سيحاول في الدورة القادمة")

            # انتظار نهاية الربع ساعة (حتى تنتهي الفترة)
            time_left = seconds_until_next_15m()
            bot.send_message(chat_id, f"⏱ انتظار نهاية السوق... (`{time_left // 60}د {time_left % 60}ث`)", parse_mode="Markdown")

            for _ in range(time_left + 5):
                if not state["active"]:
                    return
                time.sleep(1)

            # فحص النتيجة
            try:
                updated = find_market(slug)
                resolved_price = 0.5
                if updated:
                    prices = updated.get("outcomePrices", [])
                    if isinstance(prices, str):
                        prices = json.loads(prices)
                    if prices and len(prices) > 0:
                        resolved_price = float(prices[0])

                if resolved_price >= 0.95:  # ربح
                    profit = amount * (1 / resolved_price - 1)
                    state["total_pnl"] += profit
                    state["loss_streak"] = 0
                    state["current_amount"] = settings["trade_amount"]
                    bot.send_message(
                        chat_id,
                        f"✅ *ربحت!*\n"
                        f"الربح: `+{profit:.2f} USDC`\n"
                        f"إجمالي: `{state['total_pnl']:.2f} USDC`\n"
                        f"الدورة القادمة: `{state['current_amount']:.2f} USDC` (أساس)",
                        parse_mode="Markdown"
                    )
                else:  # خسارة
                    state["total_pnl"] -= amount
                    state["loss_streak"] += 1

                    if state["loss_streak"] >= settings["max_multiplications"]:
                        state["current_amount"] = settings["trade_amount"]
                        state["loss_streak"] = 0
                        bot.send_message(
                            chat_id,
                            f"❌ *خسرت* - وصل أقصى مضاعفات!\n"
                            f"الخسارة: `-{amount:.2f} USDC`\n"
                            f"إجمالي: `{state['total_pnl']:.2f} USDC`\n"
                            f"🔄 يرجع للقيمة الأساسية: `{settings['trade_amount']:.2f} USDC`",
                            parse_mode="Markdown"
                        )
                    else:
                        state["current_amount"] = amount * settings["multiplier"]
                        bot.send_message(
                            chat_id,
                            f"❌ *خسرت*\n"
                            f"الخسارة: `-{amount:.2f} USDC`\n"
                            f"إجمالي: `{state['total_pnl']:.2f} USDC`\n"
                            f"📈 الدورة القادمة: `{state['current_amount']:.2f} USDC`",
                            parse_mode="Markdown"
                        )
            except Exception as e:
                bot.send_message(chat_id, f"⚠️ لم يتحقق من النتيجة: {e}")

        except Exception as e:
            bot.send_message(chat_id, f"⚠️ خطأ: {e}")
            time.sleep(30)

    bot.send_message(chat_id, "🛑 تم إيقاف التداول")

# ============================================
# 7. لوحات المفاتيح (Keyboards)
# ============================================
def get_menu():
    """لوحة الأوامر الرئيسية"""
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add("🚀 Start Trading", "🛑 Stop Trading", "💰 My Balance", "⚙️ Settings")
    return markup

def get_settings_keyboard():
    """لوحة الإعدادات (Inline)"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(f"💵 قيمة الصفقة: {settings['trade_amount']} USDC", callback_data="set_trade_amount"),
        types.InlineKeyboardButton(f"✖️ قيمة المضاعفة: {settings['multiplier']}x", callback_data="set_multiplier"),
        types.InlineKeyboardButton(f"🔢 عدد المضاعفات: {settings['max_multiplications']}", callback_data="set_max_multiplications"),
        types.InlineKeyboardButton(f"✅ الربح الإجمالي: {settings['take_profit']} USDC", callback_data="set_take_profit"),
        types.InlineKeyboardButton(f"❌ الخسارة الإجمالية: {settings['stop_loss']} USDC", callback_data="set_stop_loss"),
    )
    return markup

def settings_text():
    """نص عرض الإعدادات"""
    return (
        "⚙️ *الإعدادات الحالية*\n\n"
        f"💵 قيمة الصفقة: `{settings['trade_amount']} USDC`\n"
        f"✖️ قيمة المضاعفة: `{settings['multiplier']}x`\n"
        f"🔢 عدد المضاعفات: `{settings['max_multiplications']}`\n"
        f"✅ الربح الإجمالي: `{settings['take_profit']} USDC`\n"
        f"❌ الخسارة الإجمالية: `{settings['stop_loss']} USDC`\n\n"
        "اضغط على أي إعداد لتغييره:"
    )

# ============================================
# 8. معالجات الأوامر (Handlers)
# ============================================
@bot.message_handler(commands=['start'])
def welcome(message):
    if not is_authorized(message):
        return
    bot.send_message(
        message.chat.id,
        "📟 *BTC 15m Martingale Bot*\nStatus: Online 🟢",
        parse_mode="Markdown",
        reply_markup=get_menu()
    )

@bot.message_handler(func=lambda m: m.text == "💰 My Balance")
def show_bal(message):
    if not is_authorized(message):
        return
    bot.send_message(message.chat.id, "🔍 جاري جلب الرصيد...")
    bal = get_balance()
    if isinstance(bal, (int, float)):
        bot.send_message(message.chat.id, f"💳 *الرصيد الحالي:*\n`{bal:.2f} USDC`", parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, f"⚠️ {bal}")

@bot.message_handler(func=lambda m: m.text == "🚀 Start Trading")
def start_trading(message):
    if not is_authorized(message):
        return
    if state["active"]:
        bot.send_message(message.chat.id, "⚠️ البوت يعمل بالفعل!")
        return
    state["active"] = True
    state["chat_id"] = message.chat.id
    state["current_amount"] = settings["trade_amount"]
    state["loss_streak"] = 0
    state["total_pnl"] = 0.0
    # بدء حلقة التداول في خيط منفصل
    t = threading.Thread(target=trading_loop, args=(message.chat.id,), daemon=True)
    t.start()

@bot.message_handler(func=lambda m: m.text == "🛑 Stop Trading")
def stop_trading(message):
    if not is_authorized(message):
        return
    state["active"] = False
    bot.send_message(message.chat.id, "🛑 *تم إيقاف البوت*\nسيتوقف بعد انتهاء الدورة الحالية.", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "⚙️ Settings")
def show_settings(message):
    if not is_authorized(message):
        return
    bot.send_message(message.chat.id, settings_text(), parse_mode="Markdown", reply_markup=get_settings_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_"))
def handle_setting_click(call):
    if ALLOWED_CHAT_ID != 0 and call.message.chat.id != ALLOWED_CHAT_ID:
        return
    chat_id = call.message.chat.id
    labels = {
        "set_trade_amount": ("💵 أدخل قيمة الصفقة (USDC):", "trade_amount"),
        "set_multiplier": ("✖️ أدخل قيمة المضاعفة (مثال 2.0):", "multiplier"),
        "set_max_multiplications": ("🔢 أدخل عدد المضاعفات الأقصى:", "max_multiplications"),
        "set_take_profit": ("✅ أدخل هدف الربح الإجمالي (USDC):", "take_profit"),
        "set_stop_loss": ("❌ أدخل حد الخسارة الإجمالية (USDC):", "stop_loss"),
    }
    if call.data in labels:
        prompt, key = labels[call.data]
        waiting_for[chat_id] = key
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, prompt)

@bot.message_handler(func=lambda m: m.chat.id in waiting_for)
def handle_setting_input(message):
    if not is_authorized(message):
        return
    chat_id = message.chat.id
    key = waiting_for.get(chat_id)
    try:
        value = float(message.text.strip())
        if key == "max_multiplications":
            value = int(value)
        settings[key] = value
        del waiting_for[chat_id]
        bot.send_message(chat_id, "✅ تم الحفظ!")
        bot.send_message(chat_id, settings_text(), parse_mode="Markdown", reply_markup=get_settings_keyboard())
    except ValueError:
        bot.send_message(chat_id, "⚠️ أدخل رقماً صحيحاً فقط:")

# ============================================
# 9. تشغيل البوت
# ============================================
if __name__ == "__main__":
    print("🤖 Bot started!")
    bot.polling(none_stop=True)
