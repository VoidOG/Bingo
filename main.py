import random
from pymongo import MongoClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# MongoDB setup
client = MongoClient("mongodb+srv://Cenzo:Cenzo123@cenzo.azbk1.mongodb.net")
db = client["bingo_bot"]
games_collection = db["games"]
players_collection = db["players"]
global_board_collection = db["global_board"]

# Game Setup
def generate_board():
    numbers = random.sample(range(1, 26), 25)
    return [numbers[i:i + 5] for i in range(0, 25, 5)]

# Format board for inline display
def format_board(board, marks):
    result = ""
    for i, row in enumerate(board):
        result += " | ".join(
            f"✅ {num}" if marks[i][j] else f"{num}"
            for j, num in enumerate(row)
        ) + "\n"
    return result

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎉 Welcome to Bingo Bot! 🎉\n"
        "Commands:\n"
        "/join - Join a game\n"
        "/endgame - End the current game\n"
        "/gamehelp - Show game rules\n"
        "/leaderboard - Show leaderboard of top players\n"
        "/globalboard - Show global board of players\n"
        "/stats - View bot stats (groups, users, games)\n"
        "/broadcast - Send a message to all users"
    )

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name

    # Check if game is already running
    game = games_collection.find_one({"chat_id": chat_id})

    if not game:
        board = generate_board()
        marks = [[False] * 5 for _ in range(5)]
        games_collection.insert_one({
            "chat_id": chat_id,
            "players": {user_id: {"name": user_name, "board": board, "marks": marks}},
            "turn": user_id,
            "winner": None,
        })
        await update.message.reply_text(f"{user_name} has joined the game! Waiting for another player.")
        return

    if user_id in game["players"]:
        await update.message.reply_text("You are already in the game!")
        return

    if len(game["players"]) >= 2:
        await update.message.reply_text("Two players are already in the game! Please wait for the next round.")
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

# Send turn notification
async def send_turn_notification(bot, chat_id, game):
    current_turn = game["turn"]
    player_name = game["players"][current_turn]["name"]
    board = game["players"][current_turn]["board"]
    keyboard = [[InlineKeyboardButton(str(num), callback_data=str(num)) for num in row] for row in board]
    await bot.send_message(
        chat_id=chat_id,
        text=f"{player_name}'s turn! Choose a number from your Bingo board.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_number_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    chat_id = str(update.effective_chat.id)
    game = games_collection.find_one({"chat_id": chat_id})

    # Check if game exists
    if not game:
        await query.answer("No game is currently running.")
        return

    # Check if the user is part of the game
    if user_id not in game["players"]:
        await query.answer("You are not playing the game! Please wait for your turn.")
        return

    # Check if it's the user's turn
    if user_id != game["turn"]:
        await query.answer("It's not your turn! Please wait for the current player to make a move.")
        return

    # Proceed with the number selection
    selected_number = int(query.data)
    player = game["players"][user_id]
    board = player["board"]
    marks = player["marks"]

    # Mark the number on the player's board
    for i, row in enumerate(board):
        if selected_number in row:
            marks[i][row.index(selected_number)] = True
            break

    # Mark one number on the opponent's board randomly
    opponent_id = next(id for id in game["players"] if id != user_id)
    opponent = game["players"][opponent_id]
    opponent_board = opponent["board"]
    opponent_marks = opponent["marks"]
    unmarked_numbers = [(i, j) for i, row in enumerate(opponent_board) for j, num in enumerate(row) if not opponent_marks[i][j]]
    if unmarked_numbers:
        i, j = random.choice(unmarked_numbers)
        opponent_marks[i][j] = True

    # Check for Bingo
    if check_bingo(marks):
        game["winner"] = user_id
        await query.message.reply_text(f"{player['name']} has won the game!")
        games_collection.delete_one({"chat_id": chat_id})
        return

    # Update the game state
    game["turn"] = opponent_id
    games_collection.update_one({"chat_id": chat_id}, {"$set": game})

    # Send the updated boards and turn notification
    await send_turn_notification(context.bot, chat_id, game)
    await query.answer(f"You selected {selected_number}")
    

# Endgame command
async def endgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    game = games_collection.find_one({"chat_id": chat_id})
    if not game:
        await update.message.reply_text("No game is currently running.")
        return

    games_collection.delete_one({"chat_id": chat_id})
    await update.message.reply_text("The current game has been ended.")

# Game help command
async def gamehelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎲 **How to play Bingo** 🎲\n"
        "1. Join a game using /join.\n"
        "2. Each player has a Bingo board. Choose a number from your board.\n"
        "3. The opponent's board will be automatically updated.\n"
        "4. Players alternate turns until one completes a row, column, or diagonal (Bingo).\n"
        "5. The first player to get Bingo wins the game!\n"
        "6. You can end the game anytime using /endgame."
    )

# Leaderboard command
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_players = players_collection.find().sort("score", -1).limit(10)
    leaderboard_text = "🏆 **Leaderboard** 🏆\n"
    for idx, player in enumerate(top_players, 1):
        leaderboard_text += f"{idx}. {player['name']} - {player['score']} points\n"
    await update.message.reply_text(leaderboard_text)

# Global board command
async def globalboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global_players = global_board_collection.find().sort("score", -1).limit(10)
    global_board_text = "🌍 **Global Leaderboard** 🌍\n"
    for idx, player in enumerate(global_players, 1):
        global_board_text += f"{idx}. {player['name']} - {player['score']} points\n"
    await update.message.reply_text(global_board_text)

# Stats command
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_groups = len(games_collection.distinct("chat_id"))
    total_users = len(players_collection.find())
    total_games = games_collection.count_documents({})
    await update.message.reply_text(
        f"📊 **Bot Stats** 📊\n"
        f"Total Groups: {total_groups}\n"
        f"Total Users: {total_users}\n"
        f"Total Games Played: {total_games}"
    )

# Broadcast command (Owner-only)
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != 6663845789:  # Replace with your owner ID
        await update.message.reply_text("You are not authorized to use this command.")
        return

    message = " ".join(context.args)
    if not message:
        await update.message.reply_text("Please provide a message to broadcast.")
        return

    all_users = players_collection.find()
    for user in all_users:
        try:
            await update.message.bot.send_message(user['user_id'], message)
        except Exception as e:
            print(f"Error sending message to {user['user_id']}: {e}")
    
    await update.message.reply_text("Broadcast message sent to all users.")

# Main function
def main():
    application = Application.builder().token("7575120190:AAFITEzx9S_-172GX7sA7kiqyAVKfTn9vvw").build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("join", join))
    application.add_handler(CommandHandler("endgame", endgame))
    application.add_handler(CommandHandler("gamehelp", gamehelp))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("globalboard", globalboard))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CallbackQueryHandler(handle_number_selection))

    application.run_polling()

if __name__ == "__main__":
    main()
