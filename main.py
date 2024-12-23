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

def generate_bingo_board():
    numbers = random.sample(range(1, 26), 25)  # Random numbers between 1 and 25
    board = [numbers[i:i+5] for i in range(0, 25, 5)]  # Create a 5x5 grid
    return board

# Function to mark a number on the board
def mark_number_on_board(board, number):
    for i, row in enumerate(board):
        for j, num in enumerate(row):
            if num == number:
                board[i][j] = None  # Mark as selected
                return True
    return False

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

async def send_bingo_board(update, context, user_id, board):
    # Format the Bingo board as a string to send in DM
    board_text = ""
    for row in board:
        board_text += " | ".join(str(num) for num in row) + "\n"

    # Send the board to the user via DM
    try:
        await context.bot.send_message(chat_id=user_id, text=f"Here is your Bingo board:\n\n{board_text}")
    except Exception as e:
        print(f"Error sending Bingo board: {e}")

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    chat_id = str(update.effective_chat.id)
    user_name = update.effective_user.first_name

    # Generate the Bingo board for the player
    board = generate_bingo_board()

    # Send the Bingo board to the player's DM
    await send_bingo_board(update, context, user_id, board)

    # Add the player to the game
    game = games_collection.find_one({"chat_id": chat_id})
    if not game:
        game = {"chat_id": chat_id, "players": {}, "turn": None, "winner": None}
        games_collection.insert_one(game)

    game["players"][user_id] = {"name": user_name, "board": board, "marks": [[False]*5 for _ in range(5)]}
    game["turn"] = user_id
    games_collection.update_one({"chat_id": chat_id}, {"$set": game})

    await update.message.reply_text(f"{user_name} has joined the game! It's your turn.")

    # Notify the other player (if any) that the game has started
    if len(game["players"]) == 2:
        await update.message.reply_text("Both players are ready. The game is starting!")

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

# Function to handle number selection
async def handle_number_selection(update, context):
    query = update.callback_query
    user_id = str(query.from_user.id)
    game = games_collection.find_one({"players": {"$in": [user_id]}})  # Find the game

    if not game:
        await query.answer("No game is currently running.")
        return

    # Get current player's turn
    current_player_id = game["turn"]
    if user_id != current_player_id:
        await query.answer("It's not your turn!")
        return

    # Get selected number
    selected_number = int(query.data)
    
    # Update player's board in DM
    player_board = game["players"][user_id]["board"]
    mark_number_on_board(player_board, selected_number)
    
    # Update opponent's board with the same number at a random position
    opponent_id = next(player for player in game["players"] if player != user_id)
    opponent_board = game["players"][opponent_id]["board"]
    mark_number_on_board(opponent_board, selected_number)

    # Check for Bingo
    if check_bingo(player_board):
        game["winner"] = user_id
        await query.message.reply_text(f"{query.from_user.first_name} has won the game!")
        games_collection.delete_one({"chat_id": game["chat_id"]})  # End game
        return

    # Update game turn
    game["turn"] = opponent_id
    games_collection.update_one({"chat_id": game["chat_id"]}, {"$set": game})

    # Send updated board to each player in their DM
    player_dm = await context.bot.send_message(user_id, "Your updated Bingo board:", reply_markup=generate_board_markup(player_board))
    opponent_dm = await context.bot.send_message(opponent_id, "Your updated Bingo board:", reply_markup=generate_board_markup(opponent_board))

    # Send updated turn notification
    await query.answer(f"You selected {selected_number}. It's now {game['turn']}'s turn.")

    # Send turn notification in group
    await context.bot.send_message(game["chat_id"], f"Next turn: {game['turn']}!")
    
    

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
