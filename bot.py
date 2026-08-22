import os
import random
import sqlite3
import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = "limelight.db"
CURRENCY = "🍋"
STARTING_BALANCE = 500
DAILY_REWARD = 250
LIME = 0x9BE564

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def db():
    return sqlite3.connect(DB_PATH)


def init_db():
    with db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 500,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                games INTEGER NOT NULL DEFAULT 0,
                last_daily TEXT
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS marriages (
                user_id INTEGER PRIMARY KEY,
                partner_id INTEGER NOT NULL,
                married_at TEXT NOT NULL
            )
        """)


def ensure_user(user_id: int):
    with db() as con:
        con.execute(
            "INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, ?)",
            (user_id, STARTING_BALANCE),
        )


def get_user(user_id: int):
    ensure_user(user_id)
    with db() as con:
        return con.execute(
            "SELECT balance, wins, losses, games, last_daily FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()


def change_balance(user_id: int, amount: int):
    ensure_user(user_id)
    with db() as con:
        con.execute(
            "UPDATE users SET balance = MAX(0, balance + ?) WHERE user_id = ?",
            (amount, user_id),
        )


def record_result(user_id: int, won: bool):
    ensure_user(user_id)
    with db() as con:
        if won:
            con.execute(
                "UPDATE users SET wins = wins + 1, games = games + 1 WHERE user_id = ?",
                (user_id,),
            )
        else:
            con.execute(
                "UPDATE users SET losses = losses + 1, games = games + 1 WHERE user_id = ?",
                (user_id,),
            )


def record_tie(user_id: int):
    ensure_user(user_id)
    with db() as con:
        con.execute("UPDATE users SET games = games + 1 WHERE user_id = ?", (user_id,))


def fmt(amount: int) -> str:
    return f"{CURRENCY} {amount:,}"


def can_bet(user_id: int, amount: int) -> bool:
    return get_user(user_id)[0] >= amount


def get_partner_id(user_id: int):
    with db() as con:
        row = con.execute("SELECT partner_id FROM marriages WHERE user_id = ?", (user_id,)).fetchone()
        return row[0] if row else None


def marry_users(user_a: int, user_b: int):
    now = datetime.now(timezone.utc).isoformat()
    with db() as con:
        con.execute("INSERT OR REPLACE INTO marriages (user_id, partner_id, married_at) VALUES (?, ?, ?)", (user_a, user_b, now))
        con.execute("INSERT OR REPLACE INTO marriages (user_id, partner_id, married_at) VALUES (?, ?, ?)", (user_b, user_a, now))


def divorce_users(user_a: int, user_b: int):
    with db() as con:
        con.execute("DELETE FROM marriages WHERE user_id IN (?, ?)", (user_a, user_b))


def ship_score(user_a: int, user_b: int) -> int:
    low, high = sorted((user_a, user_b))
    seeded = random.Random(f"limelight:{low}:{high}")
    return seeded.randint(0, 100)


@bot.event
async def on_ready():
    init_db()
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as exc:
        print(f"Command sync failed: {exc}")
    print(f"Logged in as {bot.user} ({bot.user.id})")


@bot.tree.command(name="help", description="Show Limelight's commands")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🍋 Limelight Minigames",
        description="Play games, earn virtual coins, challenge friends, and climb the leaderboard.",
        color=LIME,
    )
    embed.add_field(name="🎮 Solo games", value="`/rps` `/coinflip` `/dice` `/guess` `/trivia` `/blacktea`", inline=False)
    embed.add_field(name="👥 Multiplayer", value="`/tictactoe` `/uno` `/challenge`", inline=False)
    embed.add_field(name="💚 Social", value="`/ship` `/marry` `/partner` `/divorce`", inline=False)
    embed.add_field(name="💰 Economy", value="`/balance` `/daily` `/pay` `/leaderboard` `/stats`", inline=False)
    embed.add_field(name="🎰 Wagers", value="Optional wagers use Limelight's virtual 🍋 coins only and have no real-world value.", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="balance", description="Check a Limelight coin balance")
@app_commands.describe(member="Whose balance to view")
async def balance(interaction: discord.Interaction, member: discord.Member | None = None):
    target = member or interaction.user
    balance_value, *_ = get_user(target.id)
    await interaction.response.send_message(f"💰 **{target.display_name}** has **{fmt(balance_value)}**.")


@bot.tree.command(name="daily", description="Claim your daily Limelight coins")
async def daily(interaction: discord.Interaction):
    user_id = interaction.user.id
    _, _, _, _, last_daily = get_user(user_id)
    now = datetime.now(timezone.utc)
    if last_daily:
        last = datetime.fromisoformat(last_daily)
        next_claim = last + timedelta(hours=24)
        if now < next_claim:
            remaining = next_claim - now
            hours, rem = divmod(int(remaining.total_seconds()), 3600)
            minutes = rem // 60
            await interaction.response.send_message(f"⏳ You already claimed your daily. Try again in **{hours}h {minutes}m**.", ephemeral=True)
            return
    with db() as con:
        con.execute("UPDATE users SET balance = balance + ?, last_daily = ? WHERE user_id = ?", (DAILY_REWARD, now.isoformat(), user_id))
    await interaction.response.send_message(f"🎁 Daily claimed! You received **{fmt(DAILY_REWARD)}**.")


@bot.tree.command(name="pay", description="Give another member some Limelight coins")
@app_commands.describe(member="Member to pay", amount="Amount of coins")
async def pay(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1000000]):
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("Choose another real player.", ephemeral=True)
        return
    if not can_bet(interaction.user.id, amount):
        await interaction.response.send_message("You don't have enough coins.", ephemeral=True)
        return
    change_balance(interaction.user.id, -amount)
    change_balance(member.id, amount)
    await interaction.response.send_message(f"💸 {interaction.user.mention} paid {member.mention} **{fmt(amount)}**.")


@bot.tree.command(name="stats", description="View a player's minigame stats")
@app_commands.describe(member="Player to view")
async def stats(interaction: discord.Interaction, member: discord.Member | None = None):
    target = member or interaction.user
    balance_value, wins, losses, games, _ = get_user(target.id)
    winrate = (wins / games * 100) if games else 0
    embed = discord.Embed(title=f"📊 {target.display_name}'s Stats", color=LIME)
    embed.add_field(name="Balance", value=fmt(balance_value))
    embed.add_field(name="Wins", value=str(wins))
    embed.add_field(name="Losses", value=str(losses))
    embed.add_field(name="Games", value=str(games))
    embed.add_field(name="Win rate", value=f"{winrate:.1f}%")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leaderboard", description="Show the richest Limelight players")
async def leaderboard(interaction: discord.Interaction):
    with db() as con:
        rows = con.execute("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10").fetchall()
    if not rows:
        await interaction.response.send_message("No players yet.")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (user_id, balance_value) in enumerate(rows):
        member = interaction.guild.get_member(user_id) if interaction.guild else None
        name = member.display_name if member else f"User {user_id}"
        prefix = medals[i] if i < 3 else f"**{i + 1}.**"
        lines.append(f"{prefix} {name} — **{fmt(balance_value)}**")
    await interaction.response.send_message(embed=discord.Embed(title="🏆 Limelight Rich List", description="\n".join(lines), color=LIME))


@bot.tree.command(name="ship", description="Get a fun compatibility score for two server members")
@app_commands.describe(member1="First member", member2="Second member (defaults to you)")
async def ship(interaction: discord.Interaction, member1: discord.Member, member2: discord.Member | None = None):
    second = member2 or interaction.user
    if member1.bot or second.bot:
        await interaction.response.send_message("Pick two real server members.", ephemeral=True)
        return
    if member1.id == second.id:
        await interaction.response.send_message("💚 Self-confidence score: **100%**")
        return
    score = ship_score(member1.id, second.id)
    filled = round(score / 10)
    bar = "💚" * filled + "🤍" * (10 - filled)
    if score >= 90:
        line = "Legendary duo energy."
    elif score >= 70:
        line = "Strong match."
    elif score >= 50:
        line = "Could be a solid duo."
    elif score >= 30:
        line = "Mixed signals."
    else:
        line = "Probably better as teammates."
    embed = discord.Embed(title="💚 Limelight Ship Meter", description=f"{member1.mention} × {second.mention}\n\n{bar}\n**{score}%** — {line}", color=LIME)
    await interaction.response.send_message(embed=embed)


class MarriageProposalView(discord.ui.View):
    def __init__(self, proposer: discord.Member, target: discord.Member):
        super().__init__(timeout=60)
        self.proposer = proposer
        self.target = target

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("Only the person who was asked can answer this.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="💚")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if get_partner_id(self.proposer.id) or get_partner_id(self.target.id):
            await interaction.response.edit_message(content="That proposal can't be completed because one of you already has a partner.", view=None)
            self.stop()
            return
        marry_users(self.proposer.id, self.target.id)
        await interaction.response.edit_message(content=f"💚 {self.proposer.mention} and {self.target.mention} are now paired on Limelight!", view=None)
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="✖️")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=f"❌ {self.target.mention} declined the proposal.", view=None)
        self.stop()


@bot.tree.command(name="marry", description="Send another server member a Limelight marriage proposal")
@app_commands.describe(member="Member to propose to")
async def marry(interaction: discord.Interaction, member: discord.Member):
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("Choose another real server member.", ephemeral=True)
        return
    if get_partner_id(interaction.user.id):
        await interaction.response.send_message("You already have a partner. Use `/divorce` first.", ephemeral=True)
        return
    if get_partner_id(member.id):
        await interaction.response.send_message(f"{member.display_name} already has a partner.", ephemeral=True)
        return
    await interaction.response.send_message(f"💚 {member.mention}, {interaction.user.mention} sent you a Limelight marriage proposal!", view=MarriageProposalView(interaction.user, member))


@bot.tree.command(name="partner", description="See someone's Limelight partner")
@app_commands.describe(member="Member to check")
async def partner(interaction: discord.Interaction, member: discord.Member | None = None):
    target = member or interaction.user
    partner_id = get_partner_id(target.id)
    if not partner_id:
        await interaction.response.send_message(f"💚 **{target.display_name}** doesn't have a Limelight partner right now.")
        return
    partner_member = interaction.guild.get_member(partner_id) if interaction.guild else None
    partner_text = partner_member.mention if partner_member else f"<@{partner_id}>"
    await interaction.response.send_message(f"💚 **{target.display_name}** is paired with {partner_text}.")


@bot.tree.command(name="divorce", description="End your Limelight marriage")
async def divorce(interaction: discord.Interaction):
    partner_id = get_partner_id(interaction.user.id)
    if not partner_id:
        await interaction.response.send_message("You don't currently have a Limelight partner.", ephemeral=True)
        return
    divorce_users(interaction.user.id, partner_id)
    await interaction.response.send_message(f"💔 {interaction.user.mention}'s Limelight marriage with <@{partner_id}> has ended.")


RPS_CHOICES = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}


@bot.tree.command(name="rps", description="Play rock paper scissors against Limelight")
@app_commands.describe(choice="Your move", bet="Virtual coins to wager")
@app_commands.choices(choice=[app_commands.Choice(name="Rock", value="rock"), app_commands.Choice(name="Paper", value="paper"), app_commands.Choice(name="Scissors", value="scissors")])
async def rps(interaction: discord.Interaction, choice: app_commands.Choice[str], bet: app_commands.Range[int, 0, 1000000] = 0):
    if bet and not can_bet(interaction.user.id, bet):
        await interaction.response.send_message("You don't have enough coins for that bet.", ephemeral=True)
        return
    player = choice.value
    computer = random.choice(list(RPS_CHOICES))
    if player == computer:
        result = "tie"
    elif (player, computer) in [("rock", "scissors"), ("paper", "rock"), ("scissors", "paper")]:
        result = "win"
    else:
        result = "lose"
    if result == "win":
        reward = bet if bet else 50
        change_balance(interaction.user.id, reward)
        record_result(interaction.user.id, True)
        text = f"🏆 You win! **+{fmt(reward)}**"
    elif result == "lose":
        if bet:
            change_balance(interaction.user.id, -bet)
        record_result(interaction.user.id, False)
        text = "💥 You lose!" + (f" **-{fmt(bet)}**" if bet else "")
    else:
        record_tie(interaction.user.id)
        text = "🤝 Tie — your wager is unchanged."
    await interaction.response.send_message(f"You: {RPS_CHOICES[player]} **{player.title()}**\nLimelight: {RPS_CHOICES[computer]} **{computer.title()}**\n\n{text}")


@bot.tree.command(name="coinflip", description="Bet virtual coins on heads or tails")
@app_commands.describe(side="Heads or tails", bet="Virtual coins to wager")
@app_commands.choices(side=[app_commands.Choice(name="Heads", value="heads"), app_commands.Choice(name="Tails", value="tails")])
async def coinflip(interaction: discord.Interaction, side: app_commands.Choice[str], bet: app_commands.Range[int, 1, 1000000]):
    if not can_bet(interaction.user.id, bet):
        await interaction.response.send_message("You don't have enough coins for that bet.", ephemeral=True)
        return
    result = random.choice(["heads", "tails"])
    if side.value == result:
        change_balance(interaction.user.id, bet)
        record_result(interaction.user.id, True)
        text = f"🪙 **{result.title()}!** You won **{fmt(bet)}**."
    else:
        change_balance(interaction.user.id, -bet)
        record_result(interaction.user.id, False)
        text = f"🪙 **{result.title()}!** You lost **{fmt(bet)}**."
    await interaction.response.send_message(text)


@bot.tree.command(name="dice", description="Roll a die against Limelight")
@app_commands.describe(bet="Virtual coins to wager")
async def dice(interaction: discord.Interaction, bet: app_commands.Range[int, 0, 1000000] = 0):
    if bet and not can_bet(interaction.user.id, bet):
        await interaction.response.send_message("You don't have enough coins for that bet.", ephemeral=True)
        return
    player, computer = random.randint(1, 6), random.randint(1, 6)
    if player > computer:
        reward = bet if bet else 40
        change_balance(interaction.user.id, reward)
        record_result(interaction.user.id, True)
        result = f"🏆 You win **+{fmt(reward)}**"
    elif player < computer:
        if bet:
            change_balance(interaction.user.id, -bet)
        record_result(interaction.user.id, False)
        result = "💥 You lose" + (f" **-{fmt(bet)}**" if bet else "")
    else:
        record_tie(interaction.user.id)
        result = "🤝 Tie"
    await interaction.response.send_message(f"🎲 You rolled **{player}**\n🎲 Limelight rolled **{computer}**\n\n{result}")


@bot.tree.command(name="guess", description="Guess Limelight's number from 1 to 10")
@app_commands.describe(number="Your guess", bet="Virtual coins to wager")
async def guess(interaction: discord.Interaction, number: app_commands.Range[int, 1, 10], bet: app_commands.Range[int, 0, 1000000] = 0):
    if bet and not can_bet(interaction.user.id, bet):
        await interaction.response.send_message("You don't have enough coins for that bet.", ephemeral=True)
        return
    answer = random.randint(1, 10)
    if number == answer:
        reward = bet * 8 if bet else 150
        change_balance(interaction.user.id, reward)
        record_result(interaction.user.id, True)
        text = f"🎯 Correct! It was **{answer}**. You won **{fmt(reward)}**!"
    else:
        if bet:
            change_balance(interaction.user.id, -bet)
        record_result(interaction.user.id, False)
        text = f"❌ It was **{answer}**." + (f" You lost **{fmt(bet)}**." if bet else "")
    await interaction.response.send_message(text)


TRIVIA = [("What planet is known as the Red Planet?", "mars"), ("How many sides does a hexagon have?", "6"), ("What is the largest ocean on Earth?", "pacific"), ("What game uses creepers, redstone, and diamonds?", "minecraft"), ("What color do you get by mixing blue and yellow?", "green"), ("How many days are in a leap year?", "366"), ("What is 9 x 9?", "81"), ("Which animal is known as man's best friend?", "dog")]


@bot.tree.command(name="trivia", description="Answer a quick trivia question")
async def trivia(interaction: discord.Interaction):
    question, answer = random.choice(TRIVIA)
    await interaction.response.send_message(f"🧠 **Trivia**\n{question}\n\nYou have **15 seconds**. Type your answer in chat!")
    def check(message: discord.Message):
        return message.author.id == interaction.user.id and message.channel.id == interaction.channel_id
    try:
        message = await bot.wait_for("message", timeout=15.0, check=check)
    except asyncio.TimeoutError:
        record_result(interaction.user.id, False)
        await interaction.followup.send(f"⌛ Time! The answer was **{answer.title()}**.")
        return
    if message.content.strip().lower() == answer:
        change_balance(interaction.user.id, 100)
        record_result(interaction.user.id, True)
        await interaction.followup.send(f"✅ Correct! **+{fmt(100)}**")
    else:
        record_result(interaction.user.id, False)
        await interaction.followup.send(f"❌ Nope — the answer was **{answer.title()}**.")


BLACK_TEA_WORDS = ["apple", "planet", "orange", "silver", "castle", "dragon", "winter", "banana", "purple", "rocket", "forest", "camera", "school", "pencil", "gaming"]


@bot.tree.command(name="blacktea", description="Type a word containing the shown letters before time runs out")
async def blacktea(interaction: discord.Interaction):
    base = random.choice(BLACK_TEA_WORDS)
    start = random.randint(0, len(base) - 2)
    letters = base[start:start + 2]
    await interaction.response.send_message(f"☕ **Black Tea**\nType a word containing **{letters.upper()}** in **12 seconds**!")
    def check(message: discord.Message):
        return message.author.id == interaction.user.id and message.channel.id == interaction.channel_id
    try:
        message = await bot.wait_for("message", timeout=12.0, check=check)
    except asyncio.TimeoutError:
        record_result(interaction.user.id, False)
        await interaction.followup.send("💥 Too slow!")
        return
    word = message.content.strip().lower()
    if letters in word and len(word) >= 3 and word.isalpha():
        change_balance(interaction.user.id, 75)
        record_result(interaction.user.id, True)
        await interaction.followup.send(f"✅ **{word}** works! **+{fmt(75)}**")
    else:
        record_result(interaction.user.id, False)
        await interaction.followup.send(f"❌ That doesn't contain **{letters.upper()}**.")


class ChallengeView(discord.ui.View):
    def __init__(self, challenger: discord.Member, opponent: discord.Member, game: str, wager: int):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.opponent = opponent
        self.game = game
        self.wager = wager

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("Only the challenged player can answer.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.wager and (not can_bet(self.challenger.id, self.wager) or not can_bet(self.opponent.id, self.wager)):
            await interaction.response.edit_message(content="❌ One player no longer has enough coins.", view=None)
            self.stop()
            return
        await interaction.response.edit_message(content=f"✅ {self.opponent.mention} accepted! Starting **{self.game}**...", view=None)
        self.stop()
        if self.game == "tictactoe":
            await interaction.followup.send(f"❌ {self.challenger.mention} vs ⭕ {self.opponent.mention}" + (f" — **{fmt(self.wager)} each**" if self.wager else ""), view=TicTacToeView(self.challenger, self.opponent, self.wager))
        elif self.game == "uno":
            game = UnoGameView(self.challenger, self.opponent, self.wager)
            await game.start(interaction)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="✖️")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=f"❌ {self.opponent.mention} declined the challenge.", view=None)
        self.stop()


@bot.tree.command(name="challenge", description="Challenge another player to a wagered minigame")
@app_commands.describe(member="Player to challenge", game="Game to play", wager="Virtual coins each player wagers")
@app_commands.choices(game=[app_commands.Choice(name="Tic-Tac-Toe", value="tictactoe"), app_commands.Choice(name="UNO", value="uno")])
async def challenge(interaction: discord.Interaction, member: discord.Member, game: app_commands.Choice[str], wager: app_commands.Range[int, 0, 1000000] = 0):
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("Choose another real player.", ephemeral=True)
        return
    if wager and (not can_bet(interaction.user.id, wager) or not can_bet(member.id, wager)):
        await interaction.response.send_message("Both players need enough coins for that wager.", ephemeral=True)
        return
    view = ChallengeView(interaction.user, member, game.value, wager)
    text = f"🎮 {member.mention}, {interaction.user.mention} challenged you to **{game.name}**"
    if wager:
        text += f" for **{fmt(wager)} each**"
    await interaction.response.send_message(text + ".", view=view)


class TicTacToeButton(discord.ui.Button):
    def __init__(self, index: int):
        super().__init__(label="·", style=discord.ButtonStyle.secondary, row=index // 3)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view: TicTacToeView = self.view
        if interaction.user.id != view.current.id:
            await interaction.response.send_message("It's not your turn.", ephemeral=True)
            return
        if view.board[self.index] is not None:
            await interaction.response.send_message("That square is already taken.", ephemeral=True)
            return
        symbol = "X" if view.current.id == view.player_x.id else "O"
        view.board[self.index] = symbol
        self.label = "❌" if symbol == "X" else "⭕"
        self.style = discord.ButtonStyle.danger if symbol == "X" else discord.ButtonStyle.primary
        self.disabled = True
        winner = view.check_winner()
        if winner or all(view.board):
            for child in view.children:
                child.disabled = True
            if winner:
                win_member = view.player_x if winner == "X" else view.player_o
                lose_member = view.player_o if winner == "X" else view.player_x
                if view.wager:
                    change_balance(win_member.id, view.wager)
                    change_balance(lose_member.id, -view.wager)
                record_result(win_member.id, True)
                record_result(lose_member.id, False)
                result = f"🏆 {win_member.mention} wins!" + (f" **+{fmt(view.wager)}**" if view.wager else "")
            else:
                record_tie(view.player_x.id)
                record_tie(view.player_o.id)
                result = "🤝 It's a draw!"
            await interaction.response.edit_message(content=result, view=view)
            view.stop()
            return
        view.current = view.player_o if view.current.id == view.player_x.id else view.player_x
        await interaction.response.edit_message(content=f"🎯 {view.current.mention}'s turn", view=view)


class TicTacToeView(discord.ui.View):
    def __init__(self, player_x: discord.Member, player_o: discord.Member, wager: int = 0):
        super().__init__(timeout=180)
        self.player_x = player_x
        self.player_o = player_o
        self.current = player_x
        self.wager = wager
        self.board = [None] * 9
        for i in range(9):
            self.add_item(TicTacToeButton(i))

    def check_winner(self):
        for a, b, c in [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]:
            if self.board[a] and self.board[a] == self.board[b] == self.board[c]:
                return self.board[a]
        return None


@bot.tree.command(name="tictactoe", description="Challenge someone to Tic-Tac-Toe")
@app_commands.describe(member="Opponent", wager="Virtual coins each player wagers")
async def tictactoe(interaction: discord.Interaction, member: discord.Member, wager: app_commands.Range[int, 0, 1000000] = 0):
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("Choose another real player.", ephemeral=True)
        return
    if wager and (not can_bet(interaction.user.id, wager) or not can_bet(member.id, wager)):
        await interaction.response.send_message("Both players need enough coins for that wager.", ephemeral=True)
        return
    await interaction.response.send_message(f"❌⭕ {member.mention}, {interaction.user.mention} challenged you to Tic-Tac-Toe" + (f" for **{fmt(wager)} each**." if wager else "."), view=ChallengeView(interaction.user, member, "tictactoe", wager))


UNO_COLORS = ["Red", "Blue", "Green", "Yellow"]
UNO_EMOJI = {"Red":"🔴", "Blue":"🔵", "Green":"🟢", "Yellow":"🟡", "Wild":"🌈"}


def make_uno_deck():
    deck = []
    for color in UNO_COLORS:
        deck.append((color, "0"))
        for n in range(1, 10):
            deck.extend([(color, str(n)), (color, str(n))])
        for action in ["Skip", "Reverse", "+2"]:
            deck.extend([(color, action), (color, action)])
    deck.extend([("Wild", "Wild")] * 4)
    random.shuffle(deck)
    return deck


def card_text(card):
    return f"{UNO_EMOJI[card[0]]} {card[0]} {card[1]}"


class UnoHandSelect(discord.ui.Select):
    def __init__(self, game, player_id):
        self.game = game
        self.player_id = player_id
        options = [discord.SelectOption(label=card_text(card)[:100], value=str(i)) for i, card in enumerate(game.hands[player_id][:25])]
        super().__init__(placeholder="Choose a card to play", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        game = self.game
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("This isn't your hand.", ephemeral=True)
            return
        if interaction.user.id != game.current.id:
            await interaction.response.send_message("It's not your turn.", ephemeral=True)
            return
        idx = int(self.values[0])
        if idx >= len(game.hands[self.player_id]):
            await interaction.response.send_message("That card is no longer available.", ephemeral=True)
            return
        card = game.hands[self.player_id][idx]
        if not game.playable(card):
            await interaction.response.send_message("You can't play that card right now.", ephemeral=True)
            return
        game.hands[self.player_id].pop(idx)
        game.discard = card
        game.active_color = random.choice(UNO_COLORS) if card[0] == "Wild" else card[0]
        other = game.other_player(game.current)
        if card[1] == "+2":
            game.draw_cards(other.id, 2)
        if len(game.hands[self.player_id]) == 0:
            await interaction.response.send_message("🏆 UNO! You played your final card!", ephemeral=True)
            await game.finish(interaction, game.current)
            return
        if card[1] not in ["Skip", "Reverse", "+2"]:
            game.current = other
        await interaction.response.send_message(f"✅ Played **{card_text(card)}**.", ephemeral=True)
        await game.update_public(interaction)


class UnoPrivateView(discord.ui.View):
    def __init__(self, game, player_id):
        super().__init__(timeout=180)
        self.game = game
        self.player_id = player_id
        if game.hands[player_id]:
            self.add_item(UnoHandSelect(game, player_id))

    @discord.ui.button(label="Draw", style=discord.ButtonStyle.secondary, emoji="🃏")
    async def draw(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("This isn't your turn panel.", ephemeral=True)
            return
        if interaction.user.id != self.game.current.id:
            await interaction.response.send_message("It's not your turn.", ephemeral=True)
            return
        card = self.game.draw_cards(self.player_id, 1)[0]
        self.game.current = self.game.other_player(self.game.current)
        await interaction.response.send_message(f"🃏 You drew **{card_text(card)}**. Turn passed.", ephemeral=True)
        await self.game.update_public(interaction)


class UnoGameView(discord.ui.View):
    def __init__(self, p1: discord.Member, p2: discord.Member, wager: int = 0):
        super().__init__(timeout=300)
        self.p1, self.p2 = p1, p2
        self.current = p1
        self.wager = wager
        self.deck = make_uno_deck()
        self.hands = {p1.id: [], p2.id: []}
        for _ in range(7):
            self.hands[p1.id].append(self.deck.pop())
            self.hands[p2.id].append(self.deck.pop())
        self.discard = self.deck.pop()
        while self.discard[0] == "Wild":
            self.deck.insert(0, self.discard)
            self.discard = self.deck.pop()
        self.active_color = self.discard[0]
        self.message = None

    def other_player(self, player):
        return self.p2 if player.id == self.p1.id else self.p1

    def playable(self, card):
        return card[0] == "Wild" or card[0] == self.active_color or card[1] == self.discard[1]

    def draw_cards(self, player_id, count):
        drawn = []
        for _ in range(count):
            if not self.deck:
                self.deck = make_uno_deck()
            card = self.deck.pop()
            self.hands[player_id].append(card)
            drawn.append(card)
        return drawn

    def public_text(self):
        return f"🃏 **UNO**\nTop card: **{card_text(self.discard)}**\nActive color: **{UNO_EMOJI[self.active_color]} {self.active_color}**\n\n{self.p1.mention}: **{len(self.hands[self.p1.id])} cards**\n{self.p2.mention}: **{len(self.hands[self.p2.id])} cards**\n\n➡️ Turn: {self.current.mention}"

    async def start(self, interaction: discord.Interaction):
        self.message = await interaction.followup.send(self.public_text(), wait=True)
        await self.send_hand(interaction, self.p1)
        await self.send_hand(interaction, self.p2)

    async def send_hand(self, interaction: discord.Interaction, player: discord.Member):
        hand_text = "\n".join(f"{i+1}. {card_text(c)}" for i, c in enumerate(self.hands[player.id]))
        await interaction.followup.send(f"🃏 **Your UNO hand**\n{hand_text}\n\nUse the menu below on your turn.", view=UnoPrivateView(self, player.id), ephemeral=True)

    async def update_public(self, interaction: discord.Interaction):
        if self.message:
            await self.message.edit(content=self.public_text())
        await self.send_hand(interaction, self.current)

    async def finish(self, interaction: discord.Interaction, winner: discord.Member):
        loser = self.other_player(winner)
        if self.wager:
            change_balance(winner.id, self.wager)
            change_balance(loser.id, -self.wager)
        record_result(winner.id, True)
        record_result(loser.id, False)
        text = f"🏆 {winner.mention} wins UNO!" + (f" **+{fmt(self.wager)}**" if self.wager else "")
        if self.message:
            await self.message.edit(content=text, view=None)
        else:
            await interaction.followup.send(text)
        self.stop()


@bot.tree.command(name="uno", description="Challenge someone to a two-player UNO match")
@app_commands.describe(member="Opponent", wager="Virtual coins each player wagers")
async def uno(interaction: discord.Interaction, member: discord.Member, wager: app_commands.Range[int, 0, 1000000] = 0):
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("Choose another real player.", ephemeral=True)
        return
    if wager and (not can_bet(interaction.user.id, wager) or not can_bet(member.id, wager)):
        await interaction.response.send_message("Both players need enough coins for that wager.", ephemeral=True)
        return
    await interaction.response.send_message(f"🃏 {member.mention}, {interaction.user.mention} challenged you to UNO" + (f" for **{fmt(wager)} each**." if wager else "."), view=ChallengeView(interaction.user, member, "uno", wager))


if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Add it to your environment or .env file.")

init_db()
bot.run(TOKEN)
