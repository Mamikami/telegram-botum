import logging
import asyncio
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import ChatJoinRequest, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# --- YAPILANDIRMA ---
API_TOKEN = '8529288120:AAFxqFwAJfMR5UbiQOXHqkVYpe7vEBAxVl8'

# Admin Giriş Bilgileri
ADMIN_USER = "zeroadmin"
ADMIN_PASS = "123456"

# Loglama
logging.basicConfig(level=logging.INFO)

# Bot kurulumu
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Giriş yapmış adminlerin ID'sini hafızada tutar (Bot kapanınca sıfırlanır)
LOGGED_IN_ADMINS = set()

# Varsayılan Hoş Geldin Mesajı
DEFAULT_WELCOME = "Merhaba! Kanalımıza hoş geldin. 👋"

# --- DURUM MAKİNESİ (STATES) ---
class AdminState(StatesGroup):
    waiting_username = State()
    waiting_password = State()
    waiting_broadcast_msg = State()
    waiting_welcome_msg = State()

# --- VERİTABANI ---
async def db_baslat():
    async with aiosqlite.connect('bot_database.db') as db:
        # Kullanıcılar tablosu
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
                            user_id INTEGER PRIMARY KEY, 
                            username TEXT,
                            full_name TEXT,
                            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        # Ayarlar tablosu (Hoş geldin mesajını kaydetmek için)
        await db.execute('''CREATE TABLE IF NOT EXISTS settings (
                            key TEXT PRIMARY KEY, 
                            value TEXT)''')
        await db.commit()

async def get_welcome_message():
    async with aiosqlite.connect('bot_database.db') as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'welcome_msg'") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else DEFAULT_WELCOME

async def set_welcome_message(text):
    async with aiosqlite.connect('bot_database.db') as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('welcome_msg', ?)", (text,))
        await db.commit()

# --- KLAVYELER (BUTONLAR) ---
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

# --- HANDLERLAR: GİRİŞ SİSTEMİ ---

@dp.message(Command("panel"))
async def cmd_login(message: types.Message, state: FSMContext):
    # Eğer zaten giriş yapmışsa paneli göster
    if message.from_user.id in LOGGED_IN_ADMINS:
        await message.answer("🔓 Yönetim Paneli:", reply_markup=main_menu_keyboard())
    else:
        await message.answer("🔒 **GÜVENLİK KONTROLÜ**\nLütfen Kullanıcı Adınızı giriniz:")
        await state.set_state(AdminState.waiting_username)

@dp.message(AdminState.waiting_username)
async def process_username(message: types.Message, state: FSMContext):
    # Güvenlik: Kullanıcının yazdığı mesajı hemen sil
    try:
        await message.delete()
    except:
        pass # Yetki yoksa silinemeyebilir

    if message.text == ADMIN_USER:
        await state.update_data(username=message.text)
        msg = await message.answer("✅ Kullanıcı adı doğru.\n🔑 Lütfen **Şifreyi** giriniz:")
        # Botun sorusunu da kaydet (gerekirse silmek için)
        await state.update_data(last_bot_msg_id=msg.message_id)
        await state.set_state(AdminState.waiting_password)
    else:
        await message.answer("❌ Hatalı kullanıcı adı. İşlem iptal edildi.")
        await state.clear()

@dp.message(AdminState.waiting_password)
async def process_password(message: types.Message, state: FSMContext):
    # Güvenlik: Şifreyi hemen sil
    try:
        await message.delete()
    except:
        pass

    if message.text == ADMIN_PASS:
        LOGGED_IN_ADMINS.add(message.from_user.id)
        await message.answer("✅ **Giriş Başarılı!** Hoş geldiniz.", reply_markup=main_menu_keyboard())
        await state.clear()
    else:
        await message.answer("❌ Hatalı şifre. Erişim reddedildi.")
        await state.clear()

# --- HANDLERLAR: PANEL İŞLEMLERİ ---

@dp.callback_query(F.data == "logout")
async def cb_logout(callback: types.CallbackQuery):
    if callback.from_user.id in LOGGED_IN_ADMINS:
        LOGGED_IN_ADMINS.remove(callback.from_user.id)
    await callback.message.edit_text("🔒 Çıkış yapıldı. Tekrar girmek için /panel yazın.")

@dp.callback_query(F.data == "stats")
async def cb_stats(callback: types.CallbackQuery):
    if callback.from_user.id not in LOGGED_IN_ADMINS:
        return await callback.answer("Lütfen önce giriş yapın!", show_alert=True)
    
    async with aiosqlite.connect('bot_database.db') as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            count = await cursor.fetchone()
            total_users = count[0]
            
    await callback.message.edit_text(f"📊 **İstatistikler**\n\n👥 Toplam Üye: {total_users}", reply_markup=main_menu_keyboard())

@dp.callback_query(F.data == "broadcast")
async def cb_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in LOGGED_IN_ADMINS:
        return await callback.answer("Lütfen önce giriş yapın!", show_alert=True)
    
    await callback.message.edit_text("📢 **Duyuru Modu**\n\nTüm kullanıcılara göndermek istediğiniz mesajı yazın:", reply_markup=cancel_keyboard())
    await state.set_state(AdminState.waiting_broadcast_msg)

@dp.message(AdminState.waiting_broadcast_msg)
async def process_broadcast(message: types.Message, state: FSMContext):
    users = []
    async with aiosqlite.connect('bot_database.db') as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            users = await cursor.fetchall()
            
    msg = await message.answer(f"⏳ Duyuru {len(users)} kişiye gönderiliyor...")
    
    success = 0
    blocked = 0
    
    for user in users:
        try:
            await bot.send_message(chat_id=user[0], text=message.text)
            success += 1
            await asyncio.sleep(0.05) # Spam koruması
        except:
            blocked += 1
            
    await msg.edit_text(f"✅ **Duyuru Tamamlandı!**\n\nUlaşan: {success}\nEngellemiş/Hata: {blocked}", reply_markup=main_menu_keyboard())
    await state.clear()

@dp.callback_query(F.data == "set_welcome")
async def cb_set_welcome(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in LOGGED_IN_ADMINS:
        return await callback.answer("Yetkisiz giriş.", show_alert=True)
    
    current_msg = await get_welcome_message()
    await callback.message.edit_text(f"📝 **Hoş Geldin Mesajı**\n\nŞu anki mesaj:\n_{current_msg}_\n\nYeni mesajı aşağıya yazın:", parse_mode="Markdown", reply_markup=cancel_keyboard())
    await state.set_state(AdminState.waiting_welcome_msg)

@dp.message(AdminState.waiting_welcome_msg)
async def process_welcome_msg(message: types.Message, state: FSMContext):
    await set_welcome_message(message.text)
    await message.answer("✅ Hoş geldin mesajı güncellendi!", reply_markup=main_menu_keyboard())
    await state.clear()

@dp.callback_query(F.data == "cancel_action")
async def cb_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("İşlem iptal edildi. Ana menü:", reply_markup=main_menu_keyboard())

# --- HANDLER: KANAL KATILIM İSTEĞİ (Botun Asıl Görevi) ---
@dp.chat_join_request()
async def join_request_handler(update: ChatJoinRequest):
    # 1. İsteği onayla
    try:
        await update.approve()
    except Exception as e:
        print(f"Onay hatası: {e}")
        return

    # 2. Veritabanına kaydet
    user_id = update.from_user.id
    username = update.from_user.username
    full_name = update.from_user.full_name
    
    async with aiosqlite.connect('bot_database.db') as db:
        try:
            await db.execute("INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)", (user_id, username, full_name))
            await db.commit()
        except Exception as e:
            print(f"DB Kayıt Hatası: {e}")

    # 3. Hoş geldin mesajı gönder
    welcome_text = await get_welcome_message()
    try:
        await bot.send_message(chat_id=user_id, text=welcome_text)
    except Exception as e:
        print(f"Mesaj gönderilemedi: {e}")

# --- BAŞLATMA ---
async def main():
    await db_baslat()
    print("Bot çalışıyor... (Giriş komutu: /panel)")
    # bekleyen update'leri siler (bot kapalıyken gelenleri)
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
