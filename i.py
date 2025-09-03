import asyncio
import json
import os
import random
import string
from datetime import datetime, timedelta
from telethon import TelegramClient, events, types, Button, functions
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from collections import deque
import threading

# ===== إعدادات البوت - يجب تحديثها =====
API_ID = 18421930  # ضع API_ID الخاص بك
API_HASH = "9cf3a6feb6dfcc7c02c69eb2c286830e"  # ضع API_HASH الخاص بك
BOT_TOKEN = "5876070267:AAEgcuzcSGvW3bKxbJMY3ceJMpekqYARwQA"
D7_BOT_USERNAME = "D7Bot"
ADMIN_ID = 5841353971  # ضع ID المشرف الخاص بك

DEFAULT_ACCESS_DURATION_HOURS = 24
CONFIG_FILE = "userbot_config.json"
CODES_FILE = "codes_database.json"
QUEUE_FILE = "operations_queue.json"
LOG_FILE = "operations_log.json"

operation_queue = deque()
queue_lock = threading.Lock()
is_processing = False

ADMIN_RIGHTS = types.ChatAdminRights(
    change_info=True,
    post_messages=True,
    edit_messages=True,
    delete_messages=True,
    ban_users=True,
    invite_users=True,
    pin_messages=True,
    add_admins=True,
    manage_call=True,
    other=True,
    anonymous=False
)

# ====== إصلاح ملف الإعدادات تلقائيًا ======
def fix_config_file():
    """تأكد أن accounts هو dict وليس list، وإذا الملف قديم حوله تلقائيًا"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
            if isinstance(data.get("accounts", None), list):
                data["accounts"] = {}
                with open(CONFIG_FILE, "w") as f:
                    json.dump(data, f)
        except Exception as e:
            with open(CONFIG_FILE, "w") as f:
                json.dump({
                    "accounts": {},
                    "group_settings": {
                        "custom_name": "",
                        "custom_description": "مرحباً بالجميع",
                        "custom_message": "ايدي",
                        "delay_between_groups": 5
                    }
                }, f)

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f)

def load_json(file, default):
    if os.path.exists(file):
        try:
            with open(file, "r") as f:
                return json.load(f)
        except:
            return default
    return default

def save_queue():
    save_json(QUEUE_FILE, list(operation_queue))

def load_queue():
    global operation_queue
    operation_queue = deque(load_json(QUEUE_FILE, []))

def add_to_queue(operation):
    with queue_lock:
        operation_queue.append(operation)
        save_queue()

def get_next_operation():
    with queue_lock:
        if operation_queue:
            op = operation_queue.popleft()
            save_queue()
            return op
    return None

def get_queue_position(user_id):
    with queue_lock:
        for i, op in enumerate(operation_queue):
            if op.get('user_id') == user_id:
                return i + 1
    return 0

def save_config(data):
    save_json(CONFIG_FILE, data)

def load_config():
    return load_json(CONFIG_FILE, {
        "accounts": {},
        "group_settings": {"custom_name": "", "custom_description": "مرحباً بالجميع", "custom_message": "ايدي", "delay_between_groups": 5}
    })

def save_codes_db(data):
    save_json(CODES_FILE, data)

def load_codes_db():
    return load_json(CODES_FILE, {
        "codes": {}, "user_access": {}, "user_stats": {}, "daily_limits": {}
    })

def save_log_entry(entry):
    log = load_json(LOG_FILE, [])
    log.append(entry)
    save_json(LOG_FILE, log)

def get_last_operations(count=10):
    log = load_json(LOG_FILE, [])
    return log[-count:]

def generate_random_code():
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=6))

def create_new_code(duration_hours=None):
    codes_db = load_codes_db()
    new_code = generate_random_code()
    while new_code in codes_db["codes"]:
        new_code = generate_random_code()
    if duration_hours is None:
        duration_hours = DEFAULT_ACCESS_DURATION_HOURS
    codes_db["codes"][new_code] = {
        "used": False,
        "created_at": datetime.now().isoformat(),
        "duration_hours": duration_hours
    }
    save_codes_db(codes_db)
    return new_code, duration_hours

def use_code(code, user_id):
    codes_db = load_codes_db()
    if code not in codes_db["codes"]:
        return False, "كود غير صحيح"
    if codes_db["codes"][code]["used"]:
        return False, "الكود مستخدم مسبقاً"
    code_data = codes_db["codes"][code]
    duration_hours = code_data.get("duration_hours", DEFAULT_ACCESS_DURATION_HOURS)
    expiry_time = datetime.now() + timedelta(hours=duration_hours)
    codes_db["user_access"][str(user_id)] = {
        "granted_at": datetime.now().isoformat(),
        "expires_at": expiry_time.isoformat(),
        "code_used": code,
        "duration_hours": duration_hours
    }
    if str(user_id) not in codes_db["user_stats"]:
        codes_db["user_stats"][str(user_id)] = {"groups_created": 0, "last_activity": ""}
    codes_db["codes"][code]["used"] = True
    codes_db["codes"][code]["used_by"] = user_id
    codes_db["codes"][code]["used_at"] = datetime.now().isoformat()
    save_codes_db(codes_db)
    return True, f"تم منح الوصول لمدة {duration_hours} ساعة"

def check_user_access(user_id):
    codes_db = load_codes_db()
    user_str = str(user_id)
    if user_str not in codes_db["user_access"]:
        return False, "لا يوجد وصول"
    user_data = codes_db["user_access"][user_str]
    expiry_time = datetime.fromisoformat(user_data["expires_at"])
    if datetime.now() > expiry_time:
        del codes_db["user_access"][user_str]
        save_codes_db(codes_db)
        return False, "انتهت صلاحية الوصول"
    # تنبيه قبل انتهاء الوصول لو بقي أقل من ساعة
    if (expiry_time - datetime.now()).total_seconds() < 3600:
        return True, "⚠️ انتبه! بقي أقل من ساعة لانتهاء وصولك."
    return True, "وصول صالح"

def check_daily_limit(user_id, requested_groups):
    codes_db = load_codes_db()
    user_str = str(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    codes_db.setdefault("daily_limits", {})
    codes_db["daily_limits"].setdefault(user_str, {})
    codes_db["daily_limits"][user_str].setdefault(today, 0)
    current_usage = codes_db["daily_limits"][user_str][today]
    daily_limit = 100
    if user_id == ADMIN_ID:
        daily_limit = 1000
    if current_usage + requested_groups > daily_limit:
        return False, f"تجاوزت الحد اليومي! استخدمت {current_usage}/{daily_limit} مجموعة اليوم"
    return True, "ضمن الحد المسموح"

def update_daily_usage(user_id, groups_created):
    codes_db = load_codes_db()
    user_str = str(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    codes_db.setdefault("daily_limits", {})
    codes_db["daily_limits"].setdefault(user_str, {})
    codes_db["daily_limits"][user_str].setdefault(today, 0)
    codes_db["daily_limits"][user_str][today] += groups_created
    codes_db.setdefault("user_stats", {})
    codes_db["user_stats"].setdefault(user_str, {"groups_created": 0, "last_activity": ""})
    codes_db["user_stats"][user_str]["groups_created"] += groups_created
    codes_db["user_stats"][user_str]["last_activity"] = datetime.now().isoformat()
    save_codes_db(codes_db)

def get_user_access_info(user_id):
    codes_db = load_codes_db()
    user_str = str(user_id)
    if user_str in codes_db["user_access"]:
        user_data = codes_db["user_access"][user_str]
        expiry_time = datetime.fromisoformat(user_data["expires_at"])
        remaining_time = expiry_time - datetime.now()
        if remaining_time.total_seconds() > 0:
            hours = int(remaining_time.total_seconds() // 3600)
            minutes = int((remaining_time.total_seconds() % 3600) // 60)
            today = datetime.now().strftime("%Y-%m-%d")
            daily_usage = codes_db.get("daily_limits", {}).get(user_str, {}).get(today, 0)
            total_groups = codes_db.get("user_stats", {}).get(user_str, {}).get("groups_created", 0)
            info = f"⏰ الوقت المتبقي: {hours} ساعة و {minutes} دقيقة\n"
            info += f"📊 استخدام اليوم: {daily_usage}/100 مجموعة\n"
            info += f"🔢 إجمالي المجموعات: {total_groups}"
            return info
    return "❌ لا يوجد وصول صالح"

def get_detailed_bot_stats():
    codes_db = load_codes_db()
    config = load_config()
    total_codes = len(codes_db["codes"])
    used_codes = sum(1 for code_data in codes_db["codes"].values() if code_data["used"])
    unused_codes = total_codes - used_codes
    total_users = len(codes_db["user_access"])
    active_users = 0
    expired_users = 0
    current_time = datetime.now()
    for user_data in codes_db["user_access"].values():
        expiry_time = datetime.fromisoformat(user_data["expires_at"])
        if current_time < expiry_time:
            active_users += 1
        else:
            expired_users += 1
    total_groups_created = sum(
        stats.get("groups_created", 0)
        for stats in codes_db.get("user_stats", {}).values()
    )
    total_accounts = len(config.get("accounts", {}))
    queue_size = len(operation_queue)
    return {
        "codes": {"total": total_codes,"used": used_codes,"unused": unused_codes},
        "users": {"total": total_users,"active": active_users,"expired": expired_users},
        "accounts": total_accounts,
        "groups_created": total_groups_created,
        "queue_size": queue_size
    }

def cleanup_locked_sessions():
    for file in os.listdir('.'):
        if file.endswith('.session-journal'):
            try: os.remove(file)
            except: pass

async def setup_account_via_bot(conv):
    try:
        await conv.send_message("📲 أرسل رقم الهاتف (مثال +96477xxxxxxx):")
        msg = await conv.get_response()
        phone = msg.text.strip()
        session_file = f"userbot_{phone.replace('+', '').replace(' ', '')}.session"
        if os.path.exists(session_file):
            try: os.remove(session_file)
            except: pass
        
        client = TelegramClient(session_file, API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            await client.send_code_request(phone)
            await conv.send_message("📩 أدخل كود التحقق المرسل لك:")
            code_msg = await conv.get_response()
            code = code_msg.text.strip()
            try:
                await client.sign_in(phone, code)
            except SessionPasswordNeededError:
                await conv.send_message("🔑 أدخل كلمة المرور 2FA:")
                pwd_msg = await conv.get_response()
                password = pwd_msg.text.strip()
                await client.sign_in(password=password)
        
        config = load_config()
        new_account = {
            "phone": phone,
            "api_id": API_ID,
            "api_hash": API_HASH,
            "session": session_file
        }
        config.setdefault("accounts", {})
        config["accounts"][str(conv.chat_id)] = new_account
        save_config(config)
        await conv.send_message(f"✅ تم تسجيل Userbot وحفظ الجلسة: {session_file}")
        await client.disconnect()
    except Exception as e:
        await conv.send_message(f"❌ خطأ في تسجيل الحساب: {str(e)}")

async def send_progress_message(conv, progress, total, operation_name):
    """إرسال رسالة تحديث النسبة المئوية"""
    percentage = (progress / total) * 100
    progress_bar = "█" * int(percentage / 5) + "░" * (20 - int(percentage / 5))
    message = f"🔄 {operation_name}\n[{progress_bar}] {percentage:.1f}%\n📊 {progress}/{total}"
    return message

async def create_supergroup(client, title, group_num, total_groups, custom_description, custom_message, user_id, conv=None):
    try:
        result = await client(functions.channels.CreateChannelRequest(
            title=title,
            about=custom_description,
            megagroup=True
        ))
        channel = result.chats[0]
        await asyncio.sleep(2)
        try:
            d7 = await client.get_entity(D7_BOT_USERNAME)
            await client(functions.channels.EditAdminRequest(
                channel=channel,
                user_id=d7,
                admin_rights=ADMIN_RIGHTS,
                rank="Admin"
            ))
        except: pass
        for i in range(7):
            try:
                await client.send_message(channel, custom_message)
                await asyncio.sleep(1)
            except: pass
        
        # إرسال تحديث النسبة المئوية
        if conv and group_num % 5 == 0:  # كل 5 مجموعات
            progress_msg = await send_progress_message(conv, group_num, total_groups, "إنشاء المجموعات")
            await conv.send_message(progress_msg)
        
        save_log_entry({"user_id": user_id, "operation": "create_group", "details": title, "timestamp": datetime.now().isoformat()})
        return True
    except FloodWaitError as e:
        hours = e.seconds // 3600
        minutes = (e.seconds % 3600) // 60
        save_log_entry({"user_id": user_id, "operation": "flood_wait", "details": f"{title} - {e.seconds}s", "timestamp": datetime.now().isoformat()})
        return f"❌ مطلوب انتظار {hours} ساعة و {minutes} دقيقة قبل إنشاء مجموعات جديدة"
    except Exception as e:
        save_log_entry({"user_id": user_id, "operation": "create_group_error", "details": str(e), "timestamp": datetime.now().isoformat()})
        return False

async def extract_group_links(client, channel_username, conv=None):
    """استخراج روابط المجموعات التي تبدأ بـ Group #"""
    dialogs = await client.get_dialogs()
    sent_count = 0
    total_groups = sum(1 for dialog in dialogs if dialog.is_group and dialog.name.startswith("Group #"))
    
    for dialog in dialogs:
        if dialog.is_group and dialog.name.startswith("Group #"):
            try:
                entity = await client.get_entity(dialog.id)
                try:
                    full_info = await client(functions.channels.GetFullChannelRequest(channel=entity))
                    invite_link = getattr(full_info.full_chat, 'exported_invite', None)
                    if invite_link and getattr(invite_link, 'link', None):
                        link_to_send = f"{entity.title}: {invite_link.link}"
                    else:
                        link_to_send = f"{entity.title} | ID: {entity.id}"
                except:
                    link_to_send = f"{entity.title} | ID: {entity.id}"

                await client.send_message(channel_username, link_to_send)
                sent_count += 1
                
                # إرسال تحديث النسبة المئوية كل 5 روابط
                if conv and sent_count % 5 == 0:
                    progress_msg = await send_progress_message(conv, sent_count, total_groups, "استخراج الروابط")
                    await conv.send_message(progress_msg)
                    
            except Exception as e:
                print(f"خطأ بالكروب {getattr(dialog, 'name', dialog.id)}: {e}")
                continue
    return sent_count

async def leave_groups(client, conv=None):
    """الخروج من المجموعات التي تبدأ بـ Group"""
    exited_count = 0
    dialogs = await client.get_dialogs()
    total_groups = sum(1 for dialog in dialogs if dialog.is_group and dialog.name.startswith("Group"))
    
    for dialog in dialogs:
        if dialog.is_group and dialog.name.startswith("Group"):
            try:
                entity = await client.get_entity(dialog.id)
                await client(functions.channels.LeaveChannelRequest(channel=entity))
                exited_count += 1
                
                # إرسال تحديث النسبة المئوية كل 5 مجموعات
                if conv and exited_count % 5 == 0:
                    progress_msg = await send_progress_message(conv, exited_count, total_groups, "الخروج من المجموعات")
                    await conv.send_message(progress_msg)
                    
            except:
                continue
    return exited_count

async def delete_groups(client, user_id, count, conv=None):
    try:
        dialogs = await client.get_dialogs()
        deleted = 0
        for d in dialogs:
            if getattr(d.entity, "megagroup", False):
                try:
                    await client(functions.channels.DeleteChannelRequest(d.entity))
                    deleted += 1
                    
                    # إرسال تحديث النسبة المئوية
                    if conv and deleted % 5 == 0:
                        progress_msg = await send_progress_message(conv, deleted, count, "حذف المجموعات")
                        await conv.send_message(progress_msg)
                    
                    save_log_entry({"user_id": user_id, "operation": "delete_group", "details": d.name, "timestamp": datetime.now().isoformat()})
                    if deleted >= count:
                        break
                except Exception as e:
                    save_log_entry({"user_id": user_id, "operation": "delete_group_error", "details": str(e), "timestamp": datetime.now().isoformat()})
        return deleted
    except Exception as e:
        save_log_entry({"user_id": user_id, "operation": "delete_groups_failed", "details": str(e), "timestamp": datetime.now().isoformat()})
        return 0

async def transfer_groups(client, user_id, count, target_username, conv=None):
    try:
        dialogs = await client.get_dialogs()
        transferred = 0
        target = await client.get_entity(target_username)
        for d in dialogs:
            if getattr(d.entity, "megagroup", False):
                try:
                    await client(functions.channels.InviteToChannelRequest(d.entity, [target]))
                    transferred += 1
                    
                    # إرسال تحديث النسبة المئوية
                    if conv and transferred % 5 == 0:
                        progress_msg = await send_progress_message(conv, transferred, count, "نقل المجموعات")
                        await conv.send_message(progress_msg)
                    
                    save_log_entry({"user_id": user_id, "operation": "transfer_group", "details": f"{d.name} -> {target_username}", "timestamp": datetime.now().isoformat()})
                    if transferred >= count:
                        break
                except Exception as e:
                    save_log_entry({"user_id": user_id, "operation": "transfer_group_error", "details": str(e), "timestamp": datetime.now().isoformat()})
        return transferred
    except Exception as e:
        save_log_entry({"user_id": user_id, "operation": "transfer_groups_failed", "details": str(e), "timestamp": datetime.now().isoformat()})
        return 0

async def process_queue():
    global is_processing
    while True:
        try:
            if not is_processing and operation_queue:
                is_processing = True
                operation = get_next_operation()
                if operation:
                    await execute_operation(operation)
                is_processing = False
            await asyncio.sleep(1)
        except Exception as e:
            is_processing = False

async def execute_operation(operation):
    try:
        op_type = operation["type"]
        user_id = operation["user_id"]
        config = load_config()
        user_account = config.get("accounts", {}).get(str(user_id))
        if not user_account:
            save_log_entry({"user_id": user_id, "operation": op_type, "details": "لا يوجد حساب مرتبط", "timestamp": datetime.now().isoformat()})
            return
        client = TelegramClient(user_account["session"], user_account["api_id"], user_account["api_hash"])
        await client.start(phone=user_account["phone"])
        
        if op_type == "create_groups":
            count = operation["count"]
            success_count = 0
            group_settings = config.get("group_settings", {})
            custom_name = group_settings.get("custom_name", "")
            custom_description = group_settings.get("custom_description", "مرحباً بالجميع")
            custom_message = group_settings.get("custom_message", "ايدي")
            delay = group_settings.get("delay_between_groups", 5)
            for i in range(1, count + 1):
                title = f"{custom_name} #{i}" if custom_name else f"Group #{i}"
                result = await create_supergroup(client, title, i, count, custom_description, custom_message, user_id)
                if result == True:
                    success_count += 1
                elif isinstance(result, str):
                    break
                if i < count:
                    await asyncio.sleep(delay)
            await client.disconnect()
            if success_count > 0:
                update_daily_usage(user_id, success_count)
        elif op_type == "delete_groups":
            count = operation["count"]
            deleted = await delete_groups(client, user_id, count)
            await client.disconnect()
        elif op_type == "transfer_groups":
            count = operation["count"]
            target_username = operation["target_username"]
            transferred = await transfer_groups(client, user_id, count, target_username)
            await client.disconnect()
        elif op_type == "extract_links":
            channel_username = operation["channel_username"]
            sent_count = await extract_group_links(client, channel_username)
            await client.disconnect()
        elif op_type == "leave_groups":
            exited_count = await leave_groups(client)
            await client.disconnect()
            
        save_log_entry({"user_id": user_id, "operation": op_type, "details": "تم التنفيذ", "timestamp": datetime.now().isoformat()})
    except Exception as e:
        save_log_entry({"user_id": operation.get("user_id", "unknown"), "operation": operation.get("type", "unknown"), "details": str(e), "timestamp": datetime.now().isoformat()})

async def main():
    # التحقق من البيانات المطلوبة
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ يرجى تحديث BOT_TOKEN في الكود!")
        return
    
    fix_config_file()
    load_queue()
    cleanup_locked_sessions()
    
    if os.path.exists("bot_session.session"):
        try: os.remove("bot_session.session")
        except: pass
    
    bot_client = TelegramClient("bot_session", API_ID, API_HASH)
    await bot_client.start(bot_token=BOT_TOKEN)
    asyncio.create_task(process_queue())

    @bot_client.on(events.NewMessage(pattern="/start"))
    async def start_handler(event):
        user_id = event.sender_id
        if user_id == ADMIN_ID:
            buttons = [
                [Button.inline("إضافة حساب جديد", b"add_account")],
                [Button.inline("عرض الحسابات", b"show_accounts")],
                [Button.inline("🎫 توليد كود (مدة)", b"generate_code_custom")],
                [Button.inline("🎫 توليد كود سريع", b"generate_code")],
                [Button.inline("📊 الأكواد", b"codes_stats")],
                [Button.inline("📈 إحصائيات البوت", b"bot_stats")],
                [Button.inline("📋 سجل العمليات", b"view_log")],
                [Button.inline("⚙️ إعدادات المجموعات", b"group_settings")],
                [Button.inline("🗑️ حذف المجموعات", b"delete_groups")],
                [Button.inline("📦 نقل المجموعات", b"transfer_groups")],
                [Button.inline("🔗 استخراج الروابط", b"extract_links")],
                [Button.inline("🚪 الخروج من المجموعات", b"leave_groups")],
                [Button.inline("5", b"5"), Button.inline("10", b"10")],
                [Button.inline("15", b"15"), Button.inline("20", b"20")],
                [Button.inline("50", b"50"), Button.inline("100", b"100")],
            ]
            await event.respond("👑 مرحباً أدمن! اختر الإجراء المطلوب:", buttons=buttons)
        else:
            has_access, message = check_user_access(user_id)
            if has_access:
                buttons = [
                    [Button.inline("إضافة حساب جديد", b"add_account")],
                    [Button.inline("5", b"5"), Button.inline("10", b"10")],
                    [Button.inline("15", b"15"), Button.inline("20", b"20")],
                    [Button.inline("50", b"50")],
                    [Button.inline("🔗 استخراج الروابط", b"extract_links")],
                    [Button.inline("🚪 الخروج من المجموعات", b"leave_groups")],
                    [Button.inline("⏰ معلومات الحساب", b"check_time")],
                    [Button.inline("📊 موقعي في الطابور", b"queue_position")]
                ]
                await event.respond("✅ مرحباً! اختر الإجراء المطلوب:", buttons=buttons)
            else:
                await event.respond("🔑 أدخل الكود للوصول للبوت:")

    @bot_client.on(events.NewMessage)
    async def code_handler(event):
        user_id = event.sender_id
        if event.text.startswith('/') or user_id == ADMIN_ID:
            return
        has_access, _ = check_user_access(user_id)
        if has_access:
            return
        code = event.text.strip().upper()
        if len(code) == 6 and code.isalnum():
            success, message = use_code(code, user_id)
            if success:
                buttons = [
                    [Button.inline("إضافة حساب جديد", b"add_account")],
                    [Button.inline("5", b"5"), Button.inline("10", b"10")],
                    [Button.inline("15", b"15"), Button.inline("20", b"20")],
                    [Button.inline("50", b"50")],
                    [Button.inline("🔗 استخراج الروابط", b"extract_links")],
                    [Button.inline("🚪 الخروج من المجموعات", b"leave_groups")],
                    [Button.inline("⏰ معلومات الحساب", b"check_time")],
                    [Button.inline("📊 موقعي في الطابور", b"queue_position")]
                ]
                await event.respond(f"✅ {message}\nاختر الإجراء المطلوب:", buttons=buttons)
            else:
                await event.respond(f"❌ {message}")
        elif len(code) == 6:
            await event.respond("❌ كود خاطئ! حاول مرة أخرى:")

    @bot_client.on(events.CallbackQuery)
    async def callback_handler(event):
        async with bot_client.conversation(event.sender_id) as conv:
            if event.data == b"add_account":
                await event.answer()
                await setup_account_via_bot(conv)
            
            elif event.data == b"extract_links":
                config = load_config()
                user_account = config.get("accounts", {}).get(str(event.sender_id))
                if not user_account:
                    await conv.send_message("❌ سجل دخول Userbot أولاً.")
                    await event.answer()
                    return

                await conv.send_message("📢 أدخل يوزر القناة الذي تريد إرسال الروابط له (بدون @):")
                channel_msg = await conv.get_response()
                target_channel = channel_msg.text.strip().replace('@', '')

                client = TelegramClient(user_account["session"], user_account["api_id"], user_account["api_hash"])
                await client.start(phone=user_account["phone"])

                await conv.send_message("🔄 بدء استخراج الروابط...")
                sent_count = await extract_group_links(client, channel_username=target_channel, conv=conv)

                await client.disconnect()
                await conv.send_message(f"✅ تم إرسال روابط {sent_count} مجموعة للقناة: @{target_channel}")
                await event.answer()

            elif event.data == b"leave_groups":
                config = load_config()
                user_account = config.get("accounts", {}).get(str(event.sender_id))
                if not user_account:
                    await conv.send_message("❌ سجل دخول Userbot أولاً.")
                    await event.answer()
                    return

                client = TelegramClient(user_account["session"], user_account["api_id"], user_account["api_hash"])
                await client.start(phone=user_account["phone"])

                await conv.send_message("🔄 بدء الخروج من المجموعات...")
                exited_count = await leave_groups(client, conv=conv)

                await client.disconnect()
                await conv.send_message(f"✅ تم الخروج من {exited_count} مجموعة")
                await event.answer()
            
            elif event.data == b"show_accounts":
                config = load_config()
                accounts = config.get("accounts", {})
                txt = "📱 الحسابات المحفوظة:\n\n" if accounts else "❌ لا توجد حسابات محفوظة"
                for uid, acc in accounts.items():
                    txt += f"{uid}: {acc['phone']}\n"
                await conv.send_message(txt)
                await event.answer()
                
            elif event.data == b"generate_code":
                new_code, duration = create_new_code()
                await conv.send_message(f"🎫 كود سريع:\n`{new_code}`\n⏰ مدة الوصول: {duration} ساعة")
                await event.answer()
                
            elif event.data == b"generate_code_custom":
                await conv.send_message("⏰ أدخل عدد الساعات للوصول:")
                hours_msg = await conv.get_response()
                try:
                    custom_hours = int(hours_msg.text.strip())
                    if custom_hours <= 0:
                        await conv.send_message("❌ عدد الساعات يجب أن يكون أكبر من صفر!")
                        return
                    new_code, duration = create_new_code(custom_hours)
                    await conv.send_message(f"🎫 كود مخصص:\n`{new_code}`\n⏰ مدة الوصول: {duration} ساعة")
                except ValueError:
                    await conv.send_message("❌ يرجى إدخال رقم صحيح!")
                await event.answer()
                
            elif event.data == b"codes_stats":
                stats = get_detailed_bot_stats()
                txt = f"📊 الأكواد:\nالإجمالي: {stats['codes']['total']}\nمستخدمة: {stats['codes']['used']}\nمتاحة: {stats['codes']['unused']}"
                await conv.send_message(txt)
                await event.answer()
                
            elif event.data == b"bot_stats":
                stats = get_detailed_bot_stats()
                txt = (f"📈 البوت:\nالأكواد: {stats['codes']['total']} | المستخدمين: {stats['users']['total']}\n"
                       f"نشطين: {stats['users']['active']} | حسابات: {stats['accounts']}\n"
                       f"المجموعات: {stats['groups_created']} | الطابور: {stats['queue_size']}")
                await conv.send_message(txt)
                await event.answer()
                
            elif event.data == b"check_time":
                txt = get_user_access_info(event.sender_id)
                await conv.send_message(txt)
                await event.answer()
                
            elif event.data == b"queue_position":
                position = get_queue_position(event.sender_id)
                queue_info = (f"📊 موقعك في الطابور: #{position}\n"
                              f"⏳ العمليات المنتظرة: {len(operation_queue)}\n"
                              f"🔄 حالة: {'جاري التنفيذ' if is_processing else 'في الانتظار'}")
                await conv.send_message(queue_info)
                await event.answer()
                
            elif event.data == b"view_log":
                log = get_last_operations()
                txt = "📋 سجل العمليات الأخيرة:\n"
                for entry in log:
                    txt += f"{entry['timestamp']}: {entry['user_id']} - {entry['operation']} - {entry['details']}\n"
                await conv.send_message(txt)
                await event.answer()
                
            elif event.data == b"group_settings":
                config = load_config()
                settings = config.get("group_settings", {})
                txt = (f"⚙️ إعدادات المجموعات:\n"
                       f"اسم: {settings.get('custom_name', 'افتراضي')}\n"
                       f"وصف: {settings.get('custom_description', 'مرحباً بالجميع')}\n"
                       f"رسالة: {settings.get('custom_message', 'ايدي')}\n"
                       f"تأخير: {settings.get('delay_between_groups', 5)} ثانية\n")
                buttons = [
                    [Button.inline("📝 تغيير الاسم", b"change_name")],
                    [Button.inline("📄 تغيير الوصف", b"change_description")],
                    [Button.inline("💬 تغيير الرسالة", b"change_message")],
                    [Button.inline("⏱️ تغيير التأخير", b"change_delay")]
                ]
                await conv.send_message(txt, buttons=buttons)
                await event.answer()
                
            elif event.data == b"change_name":
                await conv.send_message("📝 أدخل الاسم الجديد:")
                name_msg = await conv.get_response()
                new_name = name_msg.text.strip()
                config = load_config()
                config["group_settings"]["custom_name"] = new_name
                save_config(config)
                await conv.send_message(f"✅ تم تحديث الاسم إلى: {new_name}")
                await event.answer()
                
            elif event.data == b"change_description":
                await conv.send_message("📄 أدخل الوصف الجديد:")
                desc_msg = await conv.get_response()
                new_desc = desc_msg.text.strip()
                config = load_config()
                config["group_settings"]["custom_description"] = new_desc
                save_config(config)
                await conv.send_message(f"✅ تم تحديث الوصف إلى: {new_desc}")
                await event.answer()
                
            elif event.data == b"change_message":
                await conv.send_message("💬 أدخل الرسالة الجديدة:")
                msg_msg = await conv.get_response()
                new_message = msg_msg.text.strip()
                config = load_config()
                config["group_settings"]["custom_message"] = new_message
                save_config(config)
                await conv.send_message(f"✅ تم تحديث الرسالة إلى: {new_message}")
                await event.answer()
                
            elif event.data == b"change_delay":
                await conv.send_message("⏱️ أدخل وقت التأخير بين المجموعات (ثواني):")
                delay_msg = await conv.get_response()
                try:
                    new_delay = int(delay_msg.text.strip())
                    config = load_config()
                    config["group_settings"]["delay_between_groups"] = new_delay
                    save_config(config)
                    await conv.send_message(f"✅ تم تحديث التأخير إلى: {new_delay} ثانية")
                except ValueError:
                    await conv.send_message("❌ يرجى إدخال رقم صحيح!")
                await event.answer()
                
            elif event.data == b"delete_groups":
                config = load_config()
                if str(event.sender_id) not in config.get("accounts", {}):
                    await conv.send_message("❌ سجل دخول Userbot أولاً.")
                    await event.answer()
                    return
                await conv.send_message("🗑️ كم مجموعة تريد حذف؟ (أدخل رقم):")
                count_msg = await conv.get_response()
                try:
                    delete_count = int(count_msg.text.strip())
                    if delete_count <= 0:
                        await conv.send_message("❌ عدد المجموعات يجب أن يكون أكبر من صفر!")
                        return
                    await conv.send_message(f"⚠️ متأكد من حذف {delete_count} مجموعة؟ اكتب 'نعم' للتأكيد:")
                    confirm_msg = await conv.get_response()
                    if confirm_msg.text.strip().lower() in ['نعم', 'yes', 'موافق']:
                        operation = {
                            "type": "delete_groups",
                            "user_id": event.sender_id,
                            "count": delete_count,
                            "timestamp": datetime.now().isoformat()
                        }
                        add_to_queue(operation)
                        position = get_queue_position(event.sender_id)
                        await conv.send_message(f"✅ تم إضافة عملية الحذف للطابور\n📊 موقعك: #{position}")
                    else:
                        await conv.send_message("❌ تم إلغاء عملية الحذف")
                except ValueError:
                    await conv.send_message("❌ يرجى إدخال رقم صحيح!")
                await event.answer()
                
            elif event.data == b"transfer_groups":
                config = load_config()
                if str(event.sender_id) not in config.get("accounts", {}):
                    await conv.send_message("❌ سجل دخول Userbot أولاً.")
                    await event.answer()
                    return
                await conv.send_message("📦 أدخل username الحساب المستقبل (بدون @):")
                username_msg = await conv.get_response()
                target_username = username_msg.text.strip().replace('@', '')
                await conv.send_message("🔢 كم مجموعة تريد نقل؟ (أدخل رقم):")
                count_msg = await conv.get_response()
                try:
                    transfer_count = int(count_msg.text.strip())
                    if transfer_count <= 0:
                        await conv.send_message("❌ عدد المجموعات يجب أن يكون أكبر من صفر!")
                        return
                    operation = {
                        "type": "transfer_groups",
                        "user_id": event.sender_id,
                        "count": transfer_count,
                        "target_username": target_username,
                        "timestamp": datetime.now().isoformat()
                    }
                    add_to_queue(operation)
                    position = get_queue_position(event.sender_id)
                    await conv.send_message(f"✅ تم إضافة عملية النقل للطابور\n📊 موقعك: #{position}\n👤 المستقبل: @{target_username}")
                except ValueError:
                    await conv.send_message("❌ يرجى إدخال رقم صحيح!")
                await event.answer()
                
            elif event.data in [b"5", b"10", b"15", b"20", b"50", b"100"]:
                user_id = event.sender_id
                count = int(event.data.decode())
                if user_id != ADMIN_ID:
                    has_access, message = check_user_access(user_id)
                    if not has_access:
                        await conv.send_message("❌ انتهت صلاحية الوصول. احصل على كود جديد من الأدمن.")
                        await event.answer()
                        return
                    can_create, limit_message = check_daily_limit(user_id, count)
                    if not can_create:
                        await conv.send_message(f"❌ {limit_message}")
                        await event.answer()
                        return
                config = load_config()
                if str(user_id) not in config.get("accounts", {}):
                    await conv.send_message("❌ سجل دخول Userbot أولاً.")
                    return
                operation = {
                    "type": "create_groups",
                    "user_id": user_id,
                    "count": count,
                    "timestamp": datetime.now().isoformat()
                }
                add_to_queue(operation)
                position = get_queue_position(user_id)
                queue_msg = (f"✅ تم إضافة طلبك للطابور\n"
                             f"📊 موقعك: #{position}\n"
                             f"📝 ستبدأ عمليتك تلقائياً عند وصول دورك\n"
                             f"💡 ستحصل على تحديثات مئوية أثناء العملية")
                await conv.send_message(queue_msg)
                await event.answer()

    print("[*] البوت جاهز! ارسل /start في تليجرام.")
    await bot_client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
