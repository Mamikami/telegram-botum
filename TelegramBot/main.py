import logging
import asyncio
import asyncpg
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ChatJoinRequest, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
# Hata türlerini yakalamak için eklemeler
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramBadRequest

# --- YAPILANDIRMA ---
API_TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", 8080))

ADMIN_USER = "zeroadmin"
ADMIN_PASS = "123456"

logging.basicConfig(level=logging.INFO)

if not API_TOKEN:
    print("HATA: TELEGRAM_TOKEN bulunamadı!")
    exit(1)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
LOGGED_IN_ADMINS = set()
DEFAULT_WELCOME = "Merhaba! Kanalımıza hoş geldin. 👋"

db_pool = None

class AdminState(StatesGroup):
    waiting_username = State()
    waiting_password = State()
    waiting_broadcast_msg = State()
    waiting_welcome_msg = State()

# --- SAHTE WEB SUNUCUSU (RENDER İÇİN) ---
async def health_check(request):
    return web.Response(text="Bot calisiyor! Render mutlu olsun :)")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"Web sunucusu {PORT} portunda başlatıldı.")

# --- VERİTABANI İŞLEMLERİ ---
async def db_baslat():
    global db_pool
    if not DATABASE_URL:
        print("HATA: DATABASE_URL bulunamadı!")
        return
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        print("Veritabanı bağlantısı başarılı.")
    except Exception as e:
        print(f"Veritabanı bağlantı hatası: {e}")
        return
    
    async with db_pool.acquire() as conn:
        await conn.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY, 
                username TEXT,
                full_name TEXT,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, value TEXT)''')

async def get_welcome_message():
    if not db_pool: return DEFAULT_WELCOME
    async with db_pool.acquire() as conn:
        value = await conn.fetchval("SELECT value FROM settings WHERE key = 'welcome_msg'")
        return value if value else DEFAULT_WELCOME

async def set_welcome_message(text):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        await conn.execute("""INSERT INTO settings (key, value) VALUES ('welcome_msg', $1)
            ON CONFLICT (key) DO UPDATE SET value = $1""", text)

async def get_all_users():
    if not db_pool: return []
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        return [row['user_id'] for row in rows]

async def get_user_count():
    if not db_pool: return 0
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM users")
        return count

async def add_user(user_id, username, full_name):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        await conn.execute("""INSERT INTO users (user_id, username, full_name) VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO NOTHING""", user_id, username, full_name)

# --- HANDLERLAR ---
def main_menu_keyboard():
    kb = [[InlineKeyboardButton(text="📊 İstatistikler", callback_data="stats"),
         InlineKeyboardButton(text="📢 Duyuru Yap", callback_data="broadcast")],
        [InlineKeyboardButton(text="📝 Hoş Geldin Mesajı Ayarla", callback_data="set_welcome")],
        [InlineKeyboardButton(text="🚪 Çıkış Yap", callback_data="logout")]]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def cancel_keyboard():
    kb = [[InlineKeyboardButton(text="❌ İptal", callback_data="cancel_action")]]
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message(Command("panel"))
async def cmd_login(message: types.Message, state: FSMContext):
    if message.from_user.id in LOGGED_IN_ADMINS:
        await message.answer("🔓 Yönetim Paneli:", reply_markup=main_menu_keyboard())
    else:
        await message.answer("🔒 **GÜVENLİK KONTROLÜ**\nLütfen Kullanıcı Adınızı giriniz:")
        await state.set_state(AdminState.waiting_username)

@dp.message(AdminState.waiting_username)
async def process_username(message: types.Message, state: FSMContext):
    try: await message.delete()
    except: pass
    if message.text == ADMIN_USER:
        await state.update_data(username=message.text)
        await message.answer("✅ Kullanıcı adı doğru. 🔑 Şifreyi giriniz:")
        await state.set_state(AdminState.waiting_password)
    else:
        await message.answer("❌ Hatalı kullanıcı adı.")
        await state.clear()

@dp.message(AdminState.waiting_password)
async def process_password(message: types.Message, state: FSMContext):
    try: await message.delete()
    except: pass
    if message.text == ADMIN_PASS:
        LOGGED_IN_ADMINS.add(message.from_user.id)
        await message.answer("✅ **Giriş Başarılı!**", reply_markup=main_menu_keyboard())
        await state.clear()
    else:
        await message.answer("❌ Hatalı şifre.")
        await state.clear()

@dp.callback_query(F.data == "logout")
async def cb_logout(callback: types.CallbackQuery):
    if callback.from_user.id in LOGGED_IN_ADMINS:
        LOGGED_IN_ADMINS.remove(callback.from_user.id)
    await callback.message.edit_text("🔒 Çıkış yapıldı.")

@dp.callback_query(F.data == "stats")
async def cb_stats(callback: types.CallbackQuery):
    if callback.from_user.id not in LOGGED_IN_ADMINS:
        return await callback.answer("Giriş yapmalısınız!", show_alert=True)
    total_users = await get_user_count()
    await callback.message.edit_text(f"📊 **İstatistikler**\n\n👥 Toplam Üye: {total_users}", reply_markup=main_menu_keyboard())

@dp.callback_query(F.data == "broadcast")
async def cb_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in LOGGED_IN_ADMINS:
        return await callback.answer("Giriş yapmalısınız!", show_alert=True)
    await callback.message.edit_text("📢 Duyuru mesajını yazın:", reply_markup=cancel_keyboard())
    await state.set_state(AdminState.waiting_broadcast_msg)

# --- GÜNCELLENMİŞ VE DETAYLI DUYURU SİSTEMİ ---
@dp.message(AdminState.waiting_broadcast_msg)
async def process_broadcast(message: types.Message, state: FSMContext):
    users = await get_all_users()
    msg = await message.answer(f"⏳ Duyuru {len(users)} kişiye gönderiliyor... Lütfen bekleyin.")
    
    success = 0
    blocked = 0
    other_errors = 0
    
    for uid in users:
        try:
            await bot.send_message(chat_id=uid, text=message.text)
            success += 1
            await asyncio.sleep(0.05) # Hızlı gönderim limiti koruması
            
        except TelegramForbiddenError:
            # Kullanıcı botu gerçekten engellemiş
            blocked += 1
            
        except TelegramRetryAfter as e:
            # Telegram "Çok hızlı gidiyorsun" dedi
            print(f"Hız limiti! {e.retry_after} saniye bekleniyor...")
            await asyncio.sleep(e.retry_after)
            # Tekrar deniyoruz
            try:
                await bot.send_message(chat_id=uid, text=message.text)
                success += 1
            except:
                other_errors += 1
                
        except Exception as e:
            # Başka bir hata (ID hatalı, Kullanıcı silinmiş, vb.)
            other_errors += 1
            print(f"⚠️ HATA (Kullanıcı ID: {uid}): {e}") # Loglara hatayı yaz
            
    await msg.edit_text(
        f"✅ **Duyuru Tamamlandı!**\n\n"
        f"✅ Ulaşan: {success}\n"
        f"🚫 Engelleyen: {blocked}\n"
        f"⚠️ Diğer Hatalar: {other_errors}\n\n"
        f"*(Diğer hataların sebebini Render Logs kısmında görebilirsin)*",
        reply_markup=main_menu_keyboard()
    )
    await state.clear()

@dp.callback_query(F.data == "set_welcome")
async def cb_set_welcome(callback: types.CallbackQuery, state: FSMContext):
    current = await get_welcome_message()
    await callback.message.edit_text(f"📝 Şu anki mesaj:\n_{current}_\n\nYeni mesajı yazın:", parse_mode="Markdown", reply_markup=cancel_keyboard())
    await state.set_state(AdminState.waiting_welcome_msg)

@dp.message(AdminState.waiting_welcome_msg)
async def process_welcome_msg(message: types.Message, state: FSMContext):
    await set_welcome_message(message.text)
    await message.answer("✅ Güncellendi!", reply_markup=main_menu_keyboard())
    await state.clear()

@dp.callback_query(F.data == "cancel_action")
async def cb_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("İptal edildi.", reply_markup=main_menu_keyboard())

@dp.chat_join_request()
async def join_request_handler(update: ChatJoinRequest):
    try:
        await update.approve()
        await add_user(update.from_user.id, update.from_user.username, update.from_user.full_name)
        welcome_text = await get_welcome_message()
        await bot.send_message(chat_id=update.from_user.id, text=welcome_text)
    except Exception as e:
        print(f"Hata: {e}")

async def main():
    await db_baslat()
    await start_web_server()
    print("Bot çalışıyor... (PostgreSQL + Detaylı Hata Analizi)")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
