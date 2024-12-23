import random
from pymongo import MongoClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# MongoDB setup
client = MongoClient("mongodb+srv://Cenzo:Cenzo123@cenzo.azbk1.mongodb.net")
db = client["bingo_bot"]
users_collection = db["users"]
games_collection = db["games"]
leaderboard_collection = db["leaderboard"]

# Owner ID
OWNER_ID = "6663845789"

# Generate a Bingo board
def generate_board():
    numbers = random.sample(range(1, 26), 25)
    return [numbers[i:i + 5] for i in range(0, 25, 5)]

# Format a Bingo board
def format_board(board, marks):
    result = ""
    for i, row in enumerate(board):
        result += " | ".join(
            f"*{num}*" if marks[i][j] else str(num)
            for j, num in enumerate(row)
        ) + "\n"
    return result

# Check for Bingo
def check_bingo(marks):
    # Horizontal and Vertical checks
    for i in range(5):
        if all(marks[i]) or all(row[i] for row in marks):
            return True
    # Diagonal checks
    if all(marks[i][i] for i in range(5)) or all(marks[i][4 - i] for i in range(5)):
        return True
    return False

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎉 Welcome to Bingo Bot! 🎉\n"
        "Commands:\n"
        "• /start - Show instructions\n"
        "• /join - Join a game\n"
        "• /endgame - End the current game\n"
        "• /broadcast - Broadcast a message (Owner only)\n"
        "• /stats - Show bot statistics (Total groups, total users, total games)\n"
        "• /leaderboard - View group leaderboard (Top 10 players)\n"
        "• /globalboard - View global leaderboard (Top 10 players)\n"
        "• /players - Show current game players\n"
        "• /gamehelp - Show game instructions"
    )

# Join command
async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name

    game = games_collection.find_one({"chat_id": chat_id})

    if not game:
        board = generate_board()
        marks = [[False] * 5 for _ in range(5)]
        games_collection.insert_one({
            "chat_id": chat_id,
            "players": {user_id: {"name": user_name, "board": board, "marks": marks}},
            "turn": None,
            "winner": None,
        })
        await update.message.reply_text(f"{user_name} has joined the game! Waiting for another player.")
        return

    if user_id in game["players"]:
        await update.message.reply_text("You are already in the game!")
        return

    if len(game["players"]) >= 2:
        await update.message.reply_text("Two players are already in the game!")
        return

    board = generate_board()
    marks = [[False] * 5 for _ in range(5)]
    game["players"][user_id] = {"name": user_name, "board": board, "marks": marks}
    game["turn"] = list(game["players"].keys())[0]
    games_collection.update_one({"chat_id": chat_id}, {"$set": game})

    players = list(game["players"].values())
    await update.message.reply_text(
        f"{user_name} has joined the game!\nThe game is starting.\n"
        f"It's {players[0]['name']}'s turn."
    )
    await send_turn_notification(context.bot, chat_id, game)

# Endgame command
async def endgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    game = games_collection.find_one({"chat_id": chat_id})
    if not game:
        await update.message.reply_text("No game is currently running.")
        return

    games_collection.delete_one({"chat_id": chat_id})
    await update.message.reply_text("The current game has been ended.")

# Broadcast command
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != OWNER_ID:
        await update.message.reply_text("You are not authorized to use this command.")
        return

    message = " ".join(context.args)
    if not message:
        await update.message.reply_text("Usage: /broadcast <message>")
        return

    users = users_collection.find()
    groups = games_collection.distinct("chat_id")

    # Send message to all users
    for user in users:
        try:
            await context.bot.send_message(user["_id"], message)
        except:
            pass

    # Send message to all groups
    for group in groups:
        try:
            await context.bot.send_message(group, message)
        except:
            pass

    await update.message.reply_text("Broadcast sent successfully!")

# Stats command
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != OWNER_ID:
        await update.message.reply_text("You are not authorized to use this command.")
        return

    # Get the total number of groups, users, and games
    total_groups = len(games_collection.distinct("chat_id"))
    total_users = users_collection.count_documents({})
    total_games = games_collection.count_documents({})

    await update.message.reply_text(
        f"📊 Bot Statistics 📊\n"
        f"• Total Groups: {total_groups}\n"
        f"• Total Users: {total_users}\n"
        f"• Total Games Played: {total_games}"
    )

# Players command
async def players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    game = games_collection.find_one({"chat_id": chat_id})

    if not game or not game["players"]:
        await update.message.reply_text("No players are currently in the game.")
        return

    player_details = "\n".join(
        [f"• {player['name']} (User ID: {user_id})" for user_id, player in game["players"].items()]
    )
    await update.message.reply_text(f"Current players:\n{player_details}")

# Leaderboard command (Top 10 players)
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    leaderboard = leaderboard_collection.find({"chat_id": chat_id}).sort("wins", -1).limit(10)

    if leaderboard.count() == 0:
        await update.message.reply_text("No leaderboard data for this group.")
        return

    text = "🏆 Group Leaderboard 🏆\n"
    for rank, entry in enumerate(leaderboard, start=1):
        text += f"{rank}. {entry['name']} - {entry['wins']} wins\n"
    await update.message.reply_text(text)

# Globalboard command (Top 10 players globally)
async def globalboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global_leaderboard = leaderboard_collection.find().sort("wins", -1).limit(10)

    if global_leaderboard.count() == 0:
        await update.message.reply_text("No global leaderboard data available.")
        return

    text = "🌐 Global Leaderboard 🌐\n"
    for rank, entry in enumerate(global_leaderboard, start=1):
        text += f"{rank}. {entry['name']} - {entry['wins']} wins\n"
    await update.message.reply_text(text)

# Game help command
async def gamehelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📝 Bingo Game Instructions 📝\n"
        "1. Players will join the game by typing /join.\n"
        "2. The game will start with 2 players.\n"
        "3. Players will receive a Bingo board with random numbers (1 to 25).\n"
        "4. Players take turns marking numbers from the board.\n"
        "5. The first player to complete a row, column, or diagonal wins!\n"
        "6. The winner is announced at the end of the game.\n"
        "7. Type /endgame to end the game.\n"
    )

# Main function
def main():
    application = Application.builder().token("7575120190:AAFITEzx9S_-172GX7sA7kiqyAVKfTn9vvw").build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("join", join))
    application.add_handler(CommandHandler("endgame", endgame))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("globalboard", globalboard))
    application.add_handler(CommandHandler("players", players))
    application.add_handler(CommandHandler("gamehelp", gamehelp))

    application.run_polling()

if __name__ == "__main__":
    main()
