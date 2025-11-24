import logging
import asyncio
import asyncpg
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import ChatJoinRequest, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# --- YAPILANDIRMA ---
# Bot Token'ı (Render'a Environment Variable olarak ekleyeceğiz)
API_TOKEN = os.getenv("TELEGRAM_TOKEN")
# Veritabanı Linki (Render'dan aldığın link)
DATABASE_URL = os.getenv("DATABASE_URL")

# Eğer bilgisayarında test ediyorsan bu satırları açıp kendi bilgilerini yazabilirsin:
# API_TOKEN = "SENİN_TOKENIN"
# DATABASE_URL = "postgresql://..."

# Admin Giriş Bilgileri
ADMIN_USER = "zeroadmin"
ADMIN_PASS = "123456"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
LOGGED_IN_ADMINS = set()
DEFAULT_WELCOME = "Merhaba! Kanalımıza hoş geldin. 👋"

# Veritabanı Bağlantı Havuzu (Global)
db_pool = None

class AdminState(StatesGroup):
    waiting_username = State()
    waiting_password = State()
    waiting_broadcast_msg = State()
    waiting_welcome_msg = State()

# --- VERİTABANI İŞLEMLERİ (POSTGRESQL) ---
async def db_baslat():
    global db_pool
    # Bağlantı havuzunu oluştur
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    
    async with db_pool.acquire() as conn:
        # Tabloları oluştur
        # Telegram ID'leri büyük olduğu için BIGINT kullanıyoruz
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY, 
                username TEXT,
                full_name TEXT,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, 
                value TEXT
            )
        ''')

async def get_welcome_message():
    async with db_pool.acquire() as conn:
        value = await conn.fetchval("SELECT value FROM settings WHERE key = 'welcome_msg'")
        return value if value else DEFAULT_WELCOME

async def set_welcome_message(text):
    async with db_pool.acquire() as conn:
        # PostgreSQL'de "UPSERT" işlemi (Varsa güncelle, yoksa ekle)
        await conn.execute("""
            INSERT INTO settings (key, value) VALUES ('welcome_msg', $1)
            ON CONFLICT (key) DO UPDATE SET value = $1
        """, text)

async def get_all_users():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        return [row['user_id'] for row in rows]

async def get_user_count():
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM users")
        return count

async def add_user(user_id, username, full_name):
    async with db_pool.acquire() as conn:
        # ON CONFLICT DO NOTHING: Eğer kullanıcı zaten varsa hata verme, geç.
        await conn.execute("""
            INSERT INTO users (user_id, username, full_name) VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO NOTHING
        """, user_id, username, full_name)

# --- KLAVYELER ---
def main_menu_keyboard():
    kb = [
        [InlineKeyboardButton(text="📊 İstatistikler", callback_data="stats"),
         InlineKeyboardButton(text="📢 Duyuru Yap", callback_data="broadcast")],
        [InlineKeyboardButton(text="📝 Hoş Geldin Mesajı Ayarla", callback_data="set_welcome")],
        [InlineKeyboardButton(text="🚪 Çıkış Yap", callback_data="logout")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def cancel_keyboard():
    kb = [[InlineKeyboardButton(text="❌ İptal", callback_data="cancel_action")]]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- HANDLERLAR ---

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

@dp.message(AdminState.waiting_broadcast_msg)
async def process_broadcast(message: types.Message, state: FSMContext):
    users = await get_all_users()
    msg = await message.answer(f"⏳ Duyuru {len(users)} kişiye gönderiliyor...")
    
    success = 0
    blocked = 0
    for uid in users:
        try:
            await bot.send_message(chat_id=uid, text=message.text)
            success += 1
            await asyncio.sleep(0.05)
        except:
            blocked += 1
            
    await msg.edit_text(f"✅ **Tamamlandı!**\nUlaşan: {success}\nHata: {blocked}", reply_markup=main_menu_keyboard())
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
    # Veritabanını başlat
    await db_baslat()
    print("Bot çalışıyor... (PostgreSQL Bağlantılı)")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())

