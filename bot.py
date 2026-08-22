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


def db(): return sqlite3.connect(DB_PATH)

def init_db():
    with db() as con:
        con.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 500, wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0, games INTEGER NOT NULL DEFAULT 0, last_daily TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS marriages (user_id INTEGER PRIMARY KEY, partner_id INTEGER NOT NULL, married_at TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS adoptions (child_id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL, adopted_at TEXT NOT NULL)")

def ensure_user(uid):
    with db() as con: con.execute("INSERT OR IGNORE INTO users (user_id,balance) VALUES (?,?)",(uid,STARTING_BALANCE))
def get_user(uid):
    ensure_user(uid)
    with db() as con: return con.execute("SELECT balance,wins,losses,games,last_daily FROM users WHERE user_id=?",(uid,)).fetchone()
def change_balance(uid,n):
    ensure_user(uid)
    with db() as con: con.execute("UPDATE users SET balance=MAX(0,balance+?) WHERE user_id=?",(n,uid))
def record_result(uid,won):
    ensure_user(uid)
    with db() as con:
        col="wins" if won else "losses"
        con.execute(f"UPDATE users SET {col}={col}+1,games=games+1 WHERE user_id=?",(uid,))
def record_tie(uid):
    ensure_user(uid)
    with db() as con: con.execute("UPDATE users SET games=games+1 WHERE user_id=?",(uid,))
def fmt(n): return f"{CURRENCY} {n:,}"
def can_bet(uid,n): return get_user(uid)[0]>=n

def get_partner_id(uid):
    with db() as con:
        r=con.execute("SELECT partner_id FROM marriages WHERE user_id=?",(uid,)).fetchone(); return r[0] if r else None
def marry_users(a,b):
    now=datetime.now(timezone.utc).isoformat()
    with db() as con:
        con.execute("INSERT OR REPLACE INTO marriages VALUES (?,?,?)",(a,b,now)); con.execute("INSERT OR REPLACE INTO marriages VALUES (?,?,?)",(b,a,now))
def divorce_users(a,b):
    with db() as con: con.execute("DELETE FROM marriages WHERE user_id IN (?,?)",(a,b))
def ship_score(a,b):
    lo,hi=sorted((a,b)); return random.Random(f"limelight:{lo}:{hi}").randint(0,100)
def get_parent_id(uid):
    with db() as con:
        r=con.execute("SELECT parent_id FROM adoptions WHERE child_id=?",(uid,)).fetchone(); return r[0] if r else None
def get_children(uid):
    with db() as con: return [r[0] for r in con.execute("SELECT child_id FROM adoptions WHERE parent_id=? ORDER BY adopted_at",(uid,)).fetchall()]
def adopt_user(parent,child):
    with db() as con: con.execute("INSERT OR REPLACE INTO adoptions VALUES (?,?,?)",(child,parent,datetime.now(timezone.utc).isoformat()))

@bot.event
async def on_ready():
    init_db()
    try: print(f"Synced {len(await bot.tree.sync())} slash commands")
    except Exception as e: print(f"Command sync failed: {e}")
    print(f"Logged in as {bot.user} ({bot.user.id})")

@bot.tree.command(name="help",description="Show Limelight's commands")
async def help_cmd(i):
    e=discord.Embed(title="🍋 Limelight Minigames",description="Play games, earn virtual coins, challenge friends, and build your server family.",color=LIME)
    e.add_field(name="🎮 Games",value="`/rps` `/coinflip` `/dice` `/guess` `/trivia` `/blacktea` `/tictactoe` `/uno` `/challenge`",inline=False)
    e.add_field(name="💚 Social",value="`/ship` `/marry` `/partner` `/divorce` `/adopt` `/family`",inline=False)
    e.add_field(name="💰 Economy",value="`/balance` `/daily` `/pay` `/leaderboard` `/stats`",inline=False)
    await i.response.send_message(embed=e)

@bot.tree.command(name="balance",description="Check a Limelight coin balance")
async def balance(i,member:discord.Member|None=None):
    t=member or i.user; await i.response.send_message(f"💰 **{t.display_name}** has **{fmt(get_user(t.id)[0])}**.")
@bot.tree.command(name="daily",description="Claim your daily Limelight coins")
async def daily(i):
    *_,last=get_user(i.user.id); now=datetime.now(timezone.utc)
    if last and now<datetime.fromisoformat(last)+timedelta(hours=24):
        d=datetime.fromisoformat(last)+timedelta(hours=24)-now; h,r=divmod(int(d.total_seconds()),3600)
        await i.response.send_message(f"⏳ Try again in **{h}h {r//60}m**.",ephemeral=True); return
    with db() as con: con.execute("UPDATE users SET balance=balance+?,last_daily=? WHERE user_id=?",(DAILY_REWARD,now.isoformat(),i.user.id))
    await i.response.send_message(f"🎁 Daily claimed! **+{fmt(DAILY_REWARD)}**")
@bot.tree.command(name="pay",description="Give another member Limelight coins")
async def pay(i,member:discord.Member,amount:app_commands.Range[int,1,1000000]):
    if member.bot or member.id==i.user.id or not can_bet(i.user.id,amount): await i.response.send_message("That payment can't be made.",ephemeral=True); return
    change_balance(i.user.id,-amount); change_balance(member.id,amount); await i.response.send_message(f"💸 {i.user.mention} paid {member.mention} **{fmt(amount)}**.")
@bot.tree.command(name="stats",description="View minigame stats")
async def stats(i,member:discord.Member|None=None):
    t=member or i.user; bal,w,l,g,_=get_user(t.id); e=discord.Embed(title=f"📊 {t.display_name}'s Stats",color=LIME); e.add_field(name="Balance",value=fmt(bal)); e.add_field(name="Wins",value=w); e.add_field(name="Losses",value=l); e.add_field(name="Games",value=g); e.add_field(name="Win rate",value=f"{w/g*100 if g else 0:.1f}%"); await i.response.send_message(embed=e)
@bot.tree.command(name="leaderboard",description="Show the richest Limelight players")
async def leaderboard(i):
    with db() as con: rows=con.execute("SELECT user_id,balance FROM users ORDER BY balance DESC LIMIT 10").fetchall()
    lines=[f"**{n}.** <@{u}> — **{fmt(b)}**" for n,(u,b) in enumerate(rows,1)]; await i.response.send_message(embed=discord.Embed(title="🏆 Limelight Rich List",description="\n".join(lines) or "No players yet.",color=LIME))

@bot.tree.command(name="ship",description="Get a fun compatibility score")
async def ship(i,member1:discord.Member,member2:discord.Member|None=None):
    b=member2 or i.user
    if member1.bot or b.bot: await i.response.send_message("Pick real server members.",ephemeral=True); return
    s=100 if member1.id==b.id else ship_score(member1.id,b.id); await i.response.send_message(embed=discord.Embed(title="💚 Limelight Ship Meter",description=f"{member1.mention} × {b.mention}\n\n{'💚'*round(s/10)}{'🤍'*(10-round(s/10))}\n**{s}%**",color=LIME))

class MarriageProposalView(discord.ui.View):
    def __init__(self,p,t): super().__init__(timeout=60); self.p=p; self.t=t
    async def interaction_check(self,i):
        if i.user.id!=self.t.id: await i.response.send_message("Only the person asked can answer.",ephemeral=True); return False
        return True
    @discord.ui.button(label="Accept",style=discord.ButtonStyle.success,emoji="💚")
    async def accept(self,i,b):
        if get_partner_id(self.p.id) or get_partner_id(self.t.id): await i.response.edit_message(content="One of you already has a partner.",view=None); return
        marry_users(self.p.id,self.t.id); await i.response.edit_message(content=f"💚 {self.p.mention} and {self.t.mention} are now paired!",view=None); self.stop()
    @discord.ui.button(label="Decline",style=discord.ButtonStyle.danger,emoji="✖️")
    async def decline(self,i,b): await i.response.edit_message(content=f"❌ {self.t.mention} declined.",view=None); self.stop()
@bot.tree.command(name="marry",description="Send a Limelight marriage proposal")
async def marry(i,member:discord.Member):
    if member.bot or member.id==i.user.id or get_partner_id(i.user.id) or get_partner_id(member.id): await i.response.send_message("That proposal can't be sent.",ephemeral=True); return
    await i.response.send_message(f"💚 {member.mention}, {i.user.mention} sent you a Limelight marriage proposal!",view=MarriageProposalView(i.user,member))
@bot.tree.command(name="partner",description="See someone's Limelight partner")
async def partner(i,member:discord.Member|None=None):
    t=member or i.user; p=get_partner_id(t.id); await i.response.send_message(f"💚 **{t.display_name}** is paired with <@{p}>." if p else f"💚 **{t.display_name}** doesn't have a partner.")
@bot.tree.command(name="divorce",description="End your Limelight marriage")
async def divorce(i):
    p=get_partner_id(i.user.id)
    if not p: await i.response.send_message("You don't have a Limelight partner.",ephemeral=True); return
    divorce_users(i.user.id,p); await i.response.send_message(f"💔 {i.user.mention}'s Limelight marriage with <@{p}> has ended.")

class AdoptView(discord.ui.View):
    def __init__(self,parent,child): super().__init__(timeout=60); self.parent=parent; self.child=child
    async def interaction_check(self,i):
        if i.user.id!=self.child.id: await i.response.send_message("Only the person being adopted can answer.",ephemeral=True); return False
        return True
    @discord.ui.button(label="Accept",style=discord.ButtonStyle.success,emoji="🏠")
    async def accept(self,i,b):
        if get_parent_id(self.child.id): await i.response.edit_message(content="You already have a Limelight parent.",view=None); return
        adopt_user(self.parent.id,self.child.id); await i.response.edit_message(content=f"🏠 {self.child.mention} joined {self.parent.mention}'s Limelight family!",view=None); self.stop()
    @discord.ui.button(label="Decline",style=discord.ButtonStyle.danger,emoji="✖️")
    async def decline(self,i,b): await i.response.edit_message(content=f"❌ {self.child.mention} declined the adoption request.",view=None); self.stop()
@bot.tree.command(name="adopt",description="Invite another member to join your Limelight family")
async def adopt(i,member:discord.Member):
    if member.bot or member.id==i.user.id: await i.response.send_message("Choose another real server member.",ephemeral=True); return
    if get_parent_id(member.id): await i.response.send_message(f"{member.display_name} already has a Limelight parent.",ephemeral=True); return
    if get_parent_id(i.user.id)==member.id: await i.response.send_message("You can't adopt your own Limelight parent.",ephemeral=True); return
    await i.response.send_message(f"🏠 {member.mention}, {i.user.mention} wants to adopt you into their Limelight family!",view=AdoptView(i.user,member))
@bot.tree.command(name="family",description="View a member's Limelight family")
async def family(i,member:discord.Member|None=None):
    t=member or i.user; p=get_parent_id(t.id); kids=get_children(t.id); partner_id=get_partner_id(t.id)
    e=discord.Embed(title=f"🏠 {t.display_name}'s Limelight Family",color=LIME); e.add_field(name="Partner",value=f"<@{partner_id}>" if partner_id else "None",inline=False); e.add_field(name="Parent",value=f"<@{p}>" if p else "None",inline=False); e.add_field(name="Children",value=" ".join(f"<@{x}>" for x in kids) if kids else "None",inline=False); await i.response.send_message(embed=e)

RPS_CHOICES={"rock":"🪨","paper":"📄","scissors":"✂️"}
@bot.tree.command(name="rps",description="Play rock paper scissors")
@app_commands.choices(choice=[app_commands.Choice(name="Rock",value="rock"),app_commands.Choice(name="Paper",value="paper"),app_commands.Choice(name="Scissors",value="scissors")])
async def rps(i,choice:app_commands.Choice[str],bet:app_commands.Range[int,0,1000000]=0):
    if bet and not can_bet(i.user.id,bet): await i.response.send_message("Not enough coins.",ephemeral=True); return
    p=choice.value; c=random.choice(list(RPS_CHOICES)); result="tie" if p==c else "win" if (p,c) in [("rock","scissors"),("paper","rock"),("scissors","paper")] else "lose"
    if result=="win": reward=bet or 50; change_balance(i.user.id,reward); record_result(i.user.id,True); text=f"🏆 You win! +{fmt(reward)}"
    elif result=="lose": change_balance(i.user.id,-bet) if bet else None; record_result(i.user.id,False); text="💥 You lose!"
    else: record_tie(i.user.id); text="🤝 Tie!"
    await i.response.send_message(f"You: {RPS_CHOICES[p]}\nLimelight: {RPS_CHOICES[c]}\n\n{text}")
@bot.tree.command(name="coinflip",description="Bet virtual coins on heads or tails")
@app_commands.choices(side=[app_commands.Choice(name="Heads",value="heads"),app_commands.Choice(name="Tails",value="tails")])
async def coinflip(i,side:app_commands.Choice[str],bet:app_commands.Range[int,1,1000000]):
    if not can_bet(i.user.id,bet): await i.response.send_message("Not enough coins.",ephemeral=True); return
    r=random.choice(["heads","tails"]); win=side.value==r; change_balance(i.user.id,bet if win else -bet); record_result(i.user.id,win); await i.response.send_message(f"🪙 **{r.title()}!** You {'won' if win else 'lost'} **{fmt(bet)}**.")
@bot.tree.command(name="dice",description="Roll a die against Limelight")
async def dice(i,bet:app_commands.Range[int,0,1000000]=0):
    if bet and not can_bet(i.user.id,bet): await i.response.send_message("Not enough coins.",ephemeral=True); return
    p,c=random.randint(1,6),random.randint(1,6)
    if p>c: change_balance(i.user.id,bet or 40); record_result(i.user.id,True); text="🏆 You win!"
    elif p<c: change_balance(i.user.id,-bet) if bet else None; record_result(i.user.id,False); text="💥 You lose!"
    else: record_tie(i.user.id); text="🤝 Tie!"
    await i.response.send_message(f"🎲 You: **{p}** | Limelight: **{c}**\n{text}")
@bot.tree.command(name="guess",description="Guess Limelight's number from 1 to 10")
async def guess(i,number:app_commands.Range[int,1,10],bet:app_commands.Range[int,0,1000000]=0):
    if bet and not can_bet(i.user.id,bet): await i.response.send_message("Not enough coins.",ephemeral=True); return
    a=random.randint(1,10); win=number==a
    if win: change_balance(i.user.id,bet*8 if bet else 150)
    elif bet: change_balance(i.user.id,-bet)
    record_result(i.user.id,win); await i.response.send_message(f"{'🎯 Correct' if win else '❌ Wrong'}! It was **{a}**.")
TRIVIA=[("What planet is known as the Red Planet?","mars"),("How many sides does a hexagon have?","6"),("What game uses creepers, redstone, and diamonds?","minecraft"),("What is 9 x 9?","81")]
@bot.tree.command(name="trivia",description="Answer a quick trivia question")
async def trivia(i):
    q,a=random.choice(TRIVIA); await i.response.send_message(f"🧠 **Trivia**\n{q}\nYou have **15 seconds**!")
    try: m=await bot.wait_for("message",timeout=15,check=lambda m:m.author.id==i.user.id and m.channel.id==i.channel_id)
    except asyncio.TimeoutError: record_result(i.user.id,False); await i.followup.send(f"⌛ Answer: **{a.title()}**"); return
    win=m.content.strip().lower()==a; change_balance(i.user.id,100) if win else None; record_result(i.user.id,win); await i.followup.send("✅ Correct!" if win else f"❌ Answer: **{a.title()}**")
@bot.tree.command(name="blacktea",description="Type a word containing the shown letters")
async def blacktea(i):
    base=random.choice(["apple","planet","orange","silver","castle","dragon","winter","banana","purple","rocket","forest","camera","school","pencil","gaming"]); n=random.randint(0,len(base)-2); letters=base[n:n+2]; await i.response.send_message(f"☕ Type a word containing **{letters.upper()}** in **12 seconds**!")
    try: m=await bot.wait_for("message",timeout=12,check=lambda m:m.author.id==i.user.id and m.channel.id==i.channel_id)
    except asyncio.TimeoutError: record_result(i.user.id,False); await i.followup.send("💥 Too slow!"); return
    word=m.content.strip().lower(); win=letters in word and len(word)>=3 and word.isalpha(); change_balance(i.user.id,75) if win else None; record_result(i.user.id,win); await i.followup.send("✅ Works!" if win else "❌ Doesn't work.")

class ChallengeView(discord.ui.View):
    def __init__(self,a,b,game,wager): super().__init__(timeout=60); self.a=a; self.b=b; self.game=game; self.wager=wager
    async def interaction_check(self,i):
        if i.user.id!=self.b.id: await i.response.send_message("Only the challenged player can answer.",ephemeral=True); return False
        return True
    @discord.ui.button(label="Accept",style=discord.ButtonStyle.success,emoji="✅")
    async def accept(self,i,b):
        if self.wager and (not can_bet(self.a.id,self.wager) or not can_bet(self.b.id,self.wager)): await i.response.edit_message(content="Not enough coins.",view=None); return
        await i.response.edit_message(content=f"✅ Accepted! Starting **{self.game}**...",view=None)
        if self.game=="tictactoe": await i.followup.send(f"❌ {self.a.mention} vs ⭕ {self.b.mention}",view=TicTacToeView(self.a,self.b,self.wager))
        else: await UnoGameView(self.a,self.b,self.wager).start(i)
    @discord.ui.button(label="Decline",style=discord.ButtonStyle.danger,emoji="✖️")
    async def decline(self,i,b): await i.response.edit_message(content="❌ Challenge declined.",view=None)
@bot.tree.command(name="challenge",description="Challenge another player")
@app_commands.choices(game=[app_commands.Choice(name="Tic-Tac-Toe",value="tictactoe"),app_commands.Choice(name="UNO",value="uno")])
async def challenge(i,member:discord.Member,game:app_commands.Choice[str],wager:app_commands.Range[int,0,1000000]=0):
    if member.bot or member.id==i.user.id: await i.response.send_message("Choose another player.",ephemeral=True); return
    await i.response.send_message(f"🎮 {member.mention}, {i.user.mention} challenged you to **{game.name}**!",view=ChallengeView(i.user,member,game.value,wager))

class TicTacToeButton(discord.ui.Button):
    def __init__(self,n): super().__init__(label="·",style=discord.ButtonStyle.secondary,row=n//3); self.n=n
    async def callback(self,i):
        v=self.view
        if i.user.id!=v.current.id or v.board[self.n]: await i.response.send_message("You can't play there right now.",ephemeral=True); return
        x="X" if v.current.id==v.x.id else "O"; v.board[self.n]=x; self.label="❌" if x=="X" else "⭕"; self.disabled=True
        win=v.winner()
        if win or all(v.board):
            for c in v.children:c.disabled=True
            if win:
                w=v.x if win=="X" else v.o; l=v.o if win=="X" else v.x; change_balance(w.id,v.wager) if v.wager else None; change_balance(l.id,-v.wager) if v.wager else None; record_result(w.id,True); record_result(l.id,False); text=f"🏆 {w.mention} wins!"
            else: record_tie(v.x.id); record_tie(v.o.id); text="🤝 Draw!"
            await i.response.edit_message(content=text,view=v); return
        v.current=v.o if v.current.id==v.x.id else v.x; await i.response.edit_message(content=f"🎯 {v.current.mention}'s turn",view=v)
class TicTacToeView(discord.ui.View):
    def __init__(self,x,o,w=0): super().__init__(timeout=180); self.x=x; self.o=o; self.current=x; self.wager=w; self.board=[None]*9; [self.add_item(TicTacToeButton(n)) for n in range(9)]
    def winner(self):
        for a,b,c in [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]:
            if self.board[a] and self.board[a]==self.board[b]==self.board[c]: return self.board[a]
@bot.tree.command(name="tictactoe",description="Challenge someone to Tic-Tac-Toe")
async def tictactoe(i,member:discord.Member,wager:app_commands.Range[int,0,1000000]=0): await i.response.send_message(f"❌⭕ {member.mention}, challenge from {i.user.mention}!",view=ChallengeView(i.user,member,"tictactoe",wager))

UNO_COLORS=["Red","Blue","Green","Yellow"]; UNO_EMOJI={"Red":"🔴","Blue":"🔵","Green":"🟢","Yellow":"🟡","Wild":"🌈"}
def make_uno_deck():
    d=[]
    for c in UNO_COLORS:
        d.append((c,"0"))
        for n in range(1,10): d.extend([(c,str(n))]*2)
        for a in ["Skip","Reverse","+2"]: d.extend([(c,a)]*2)
    d.extend([("Wild","Wild")]*4); random.shuffle(d); return d
def card_text(c): return f"{UNO_EMOJI[c[0]]} {c[0]} {c[1]}"
class UnoHandSelect(discord.ui.Select):
    def __init__(self,g,p): self.g=g;self.p=p;super().__init__(placeholder="Choose a card",options=[discord.SelectOption(label=card_text(c),value=str(n)) for n,c in enumerate(g.hands[p][:25])])
    async def callback(self,i):
        g=self.g
        if i.user.id!=self.p or i.user.id!=g.current.id: await i.response.send_message("Not your turn.",ephemeral=True); return
        n=int(self.values[0]); c=g.hands[self.p][n]
        if not g.playable(c): await i.response.send_message("Can't play that card.",ephemeral=True); return
        g.hands[self.p].pop(n); g.discard=c; g.active_color=random.choice(UNO_COLORS) if c[0]=="Wild" else c[0]; other=g.other(g.current)
        if c[1]=="+2": g.draw(other.id,2)
        if not g.hands[self.p]: await i.response.send_message("🏆 UNO!",ephemeral=True); await g.finish(i,g.current); return
        if c[1] not in ["Skip","Reverse","+2"]: g.current=other
        await i.response.send_message(f"✅ Played {card_text(c)}",ephemeral=True); await g.update(i)
class UnoPrivateView(discord.ui.View):
    def __init__(self,g,p): super().__init__(timeout=180);self.g=g;self.p=p;self.add_item(UnoHandSelect(g,p))
    @discord.ui.button(label="Draw",style=discord.ButtonStyle.secondary,emoji="🃏")
    async def draw_btn(self,i,b):
        if i.user.id!=self.p or i.user.id!=self.g.current.id: await i.response.send_message("Not your turn.",ephemeral=True); return
        c=self.g.draw(self.p,1)[0];self.g.current=self.g.other(self.g.current);await i.response.send_message(f"🃏 Drew {card_text(c)}",ephemeral=True);await self.g.update(i)
class UnoGameView:
    def __init__(self,a,b,w=0):
        self.a=a;self.b=b;self.current=a;self.wager=w;self.deck=make_uno_deck();self.hands={a.id:[],b.id:[]}
        for _ in range(7):self.hands[a.id].append(self.deck.pop());self.hands[b.id].append(self.deck.pop())
        self.discard=self.deck.pop();self.active_color=self.discard[0] if self.discard[0]!="Wild" else random.choice(UNO_COLORS);self.message=None
    def other(self,p):return self.b if p.id==self.a.id else self.a
    def playable(self,c):return c[0]=="Wild" or c[0]==self.active_color or c[1]==self.discard[1]
    def draw(self,p,n):
        out=[]
        for _ in range(n):
            if not self.deck:self.deck=make_uno_deck()
            c=self.deck.pop();self.hands[p].append(c);out.append(c)
        return out
    def text(self):return f"🃏 **UNO**\nTop: **{card_text(self.discard)}**\n{self.a.mention}: {len(self.hands[self.a.id])} cards\n{self.b.mention}: {len(self.hands[self.b.id])} cards\n➡️ {self.current.mention}'s turn"
    async def start(self,i):self.message=await i.followup.send(self.text(),wait=True);await self.send_hand(i,self.a);await self.send_hand(i,self.b)
    async def send_hand(self,i,p):await i.followup.send("🃏 **Your hand**\n"+"\n".join(card_text(c) for c in self.hands[p.id]),view=UnoPrivateView(self,p.id),ephemeral=True)
    async def update(self,i):await self.message.edit(content=self.text());await self.send_hand(i,self.current)
    async def finish(self,i,w):
        l=self.other(w);change_balance(w.id,self.wager) if self.wager else None;change_balance(l.id,-self.wager) if self.wager else None;record_result(w.id,True);record_result(l.id,False);await self.message.edit(content=f"🏆 {w.mention} wins UNO!")
@bot.tree.command(name="uno",description="Challenge someone to UNO")
async def uno(i,member:discord.Member,wager:app_commands.Range[int,0,1000000]=0): await i.response.send_message(f"🃏 {member.mention}, UNO challenge from {i.user.mention}!",view=ChallengeView(i.user,member,"uno",wager))

if not TOKEN: raise RuntimeError("DISCORD_TOKEN is missing.")
init_db();bot.run(TOKEN)
