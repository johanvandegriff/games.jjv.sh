from flask import render_template
import sys, cgi, json, datetime, re, time, decimal, subprocess, random, threading, os, pymongo

from nav import nav #file in same dir

ROOT_DIR = "/srv/boggle"
# GAMES_FILE = ROOT_DIR + "/games.json"
# GAMES_LOCK_FILE = ROOT_DIR + "/games.json.lock"

DEFINITIONS_FILE = ROOT_DIR + '/lists/CollinsScrabbleWords2019WithDefinitions.json'
WORD_LIST_FILE = ROOT_DIR + '/lists/CollinsScrabbleWords2019.json'

# definitions = json.load(open(DEFINITIONS_FILE,'r'))
# wordList = json.load(open(WORD_LIST_FILE,'r'))

# remove games that are finished after this many seconds
ARCHIVE_TIMEOUT = 30 #archive a COMPLETED game but keep in the lobby
REMOVE_COMPLETED_FROM_LOBBY_TIMEOUT = 5*60 #remove a COMPLETED game from the lobby
REMOVE_STALE_FROM_LOBBY_TIMEOUT = 2*60*60 #remove a NOT STARTED game from lobby

EXTRA_SECONDS_TO_SUBMIT = 1

#all the dice found in boggle deluxe
BOGGLE_DICE = [
        ['O','O','O','T','T','U'],
        ['D','H','H','N','O','T'],
        ['N','O','U','T','O','W'],
        ['A','A','A','S','F','R'],
        ['A','E','E','M','U','G'],
        ['A','E','N','N','M','G'],
        ['A','D','E','N','N','N'],
        ['D','D','N','R','L','O'],
        ['C','C','T','S','N','W'],
        ['F','S','I','P','R','Y'],
        ['A','E','E','E','E','M'],
        ['I','R','R','P','H','Y'],
        ['E','O','T','T','T','M'],
        ['A','A','F','I','S','R'],
        ['D','O','L','H','N','R'],
        ['C','E','S','P','T','I'],
        ['A','A','E','E','E','E'],
        ['E','I','I','I','T','T'],
        ['A','F','I','S','R','Y'],
        ['C','E','P','I','T','L'],
        ['E','N','S','S','S','U'],
        ['C','E','I','I','L','T'],
        ['D','H','H','O','L','R'],
        ['G','O','V','R','R','W'],
        ['K','Z','X','B','J','Qu']
]

#the boggle alphabet
ALPHABET = ['A','B','C','D','E','F','G','H','I','J','K','L','M',
            'N','O','P','Qu','R','S','T','U','V','W','X','Y','Z']

DB_NAME = "boggle"
COLL_NAME = "games"

with open("/srv/boggle/mongodb-url.txt", 'r') as f:
    DB_URL = f.read()

dbClient = pymongo.MongoClient(DB_URL)
db = dbClient[DB_NAME]
coll = db[COLL_NAME]

wordList = json.load(open(WORD_LIST_FILE,'r'))


#invitations to play again. the key is the game ID that players are invited from,
#  and the value is the new game they are invited to.
invitations = {}


#replace quotes
def rq(s):
  return s.replace("'", "&apos;").replace('"', '&quot;')
  #return cgi.escape(s).replace("'", "&apos;").replace('"', '&quot;')

def create(size=5, letters=None, minutes=3):
    if letters is None:
        if size >=5:
            letters = 4
        elif size == 4:
            letters = 3
        else:
            letters = 2

    dice = [] #no dice

    #until we have enough dice for this board size
    while len(dice) < size*size:
        #add a complete set of standard dice
        dice.extend(BOGGLE_DICE[:])
    #if the size is 5 or less, only 1 set is required
    #if the size is 6 or 7, 2 sets are required, etc.

    random.shuffle(dice)

    #construct the board, nested item-by-item
    board = [[dice[i*size+j][random.randint(0,5)] for j in range(size)] for i in range(size)]

    #construct a dict with all the info
    game = {
        "size": size,
        "letters": letters,
        "minutes": minutes,
        "board": board,
        "isStarted": False,
        "isDone": False,
        "isArchived": False,
        "players": [],
        "timeCreatedSeconds": int(time.time())
    }
    return game

def calculatePoints(word):
    length = len(word)
    if length > 8: length = 8
    return [0,1,1,1,1,2,3,5,11][length]

#x, y: the current position on the board
#word: the current word
#used: the spots the word has letters from 
# def solve_aux(x, y, word, used, board, words, found, size):
#     myused = used[:]

#     myused.append([x,y]); #use the current spot
#     myword = word + board[x][y].lower() #add on to the word

#     if myword in words: #if the word is in the list of possible words
#         found.append(myword)
#         # found[myword] = myused
#         words.remove(myword)
#     if not any(re.search("^" + myword, word) for word in words):
#         return
#     for newx in range(x-1,x+2): # +2 because range() is exclusive on the upper bound
#         for newy in range(y-1,y+2):
#             if (newx>=0 and newy>=0 and newx<size and newy<size and not [newx,newy] in myused):
#                 solve_aux(newx, newy, myword, myused, board, words, found, size)

def solve(game):
    start = time.time()
    board = game["board"]
    minWordLength = game["letters"]
    size = len(board)

    quantities = [] #the quantities of each letter

    excluded = [] #which letters are not on the board
    for letter in ALPHABET:
        excluded.append(letter) #copy the alphabet to excluded
        quantities.append(0) #fill quantities with 0's
        for letter2 in ALPHABET:
            excluded.append(letter + letter2)
    for x in range(size):
        for y in range(size):
            letter = board[x][y]
            quantities[ALPHABET.index(letter)] += 1 #increase the quantity of the letter
            if letter in excluded: #if the letter is in excluded
                excluded.remove(letter) #remove the letter from excluded
            if letter == 'Qu' and 'U' in excluded: #if the letter is in excluded
                excluded.remove('U') #remove the letter from excluded
            for newx in range(x-1,x+2): # +2 because range() is exclusive on the upper bound
                for newy in range(y-1,y+2):
                    if (newx>=0 and newy>=0 and newx<size and newy<size
                            and not (newx == x and newy == y)):
                        newletter = board[newx][newy]
                        seq = letter + newletter
                        if seq in excluded: #if the sequence is in excluded
                            excluded.remove(seq) #remove the sequence from excluded
                        if letter == 'Qu':
                            seq = 'U' + newletter
                        if seq in excluded: #if the sequence is in excluded
                            excluded.remove(seq) #remove the sequence from excluded

    #increase the number of U's by the number of Qu's
    quantities[ALPHABET.index('U')] += quantities[ALPHABET.index('Qu')]

    # words = [] #the list of possible words
    found = []
    
    wordList = json.load(open(WORD_LIST_FILE,'r'))
    for line in wordList: #sort through each word
        if len(line) >= minWordLength: #if the word is long enough
            #if the word does not have too many of any letter
            if not any(line.count(ALPHABET[i].lower()) > quantities[i] for i in range(len(ALPHABET))):
                #if there are no letters not on the board in this word
                if not any(letter.lower() in line for letter in excluded):
                    # words.append(line); #add the word to the list of possible words
                    if isWordValid(game, line, None):
                        found.append(line)

    score = 0
    #found = []
    # found = {}

    # for x in range(size):
    #     for y in range(size):
    #         used = []
    #         word = ""
    #         solve_aux(x, y, word, used, board, words, found, size)
    
    score = 0
    for word in found:
        score += calculatePoints(word)
    
    game["words"] = found
    # game["paths"] = found
    game["maxScore"] = score
    game["maxWords"] = len(found)
    game["secondsToSolve"] = time.time() - start
    return game

def isWordValidAux(board, word, x, y, used, size):
    if len(word) == 0: return True
    myused = used[:]
    myused.append([x,y]); #use the current spot
    l = board[x][y].lower()
    if l == "qu":
        if len(word) < 2 or word[0:2] != "qu": return False
        if word == "qu": return True
        newword = word[2:]
    else:
        if word[0] != l: return False
        if word == l: return True
        newword = word[1:]
            
    for newx in range(x-1,x+2): # +2 because range() is exclusive on the upper bound
        for newy in range(y-1,y+2):
            if (newx>=0 and newy>=0 and newx<size and newy<size and not [newx,newy] in myused):
                if isWordValidAux(board, newword, newx, newy, myused, size):
                    return True
    return False


def isWordValid(game, word, wordList):
    if len(word) < game["letters"] or (wordList is not None and not word in wordList):
        return False
    board = game["board"]
    size = len(board)
    if len(word) <= size*size:
        for x in range(size):
            for y in range(size):
                if isWordValidAux(board, word, x, y, [], size):
                     return True
    return False


def getGameByID(id):
    return coll.find_one({"_id": id})

def deleteGameByID(id):
    coll.delete_one({"_id": id})

def getAllIDs():
    return [x["_id"] for x in coll.find({}, {"_id": 1})]
def newGameID():
    allIDs = getAllIDs()
    if len(allIDs) == 0: #if there are no IDs, max([]) will fail
        return 0 #so return 1 so it starts with game #0
    else:
        return max(getAllIDs())+1

def updateAttr(game, attr):
    coll.update_one({"_id": game["_id"]}, {"$set": {attr: game[attr]}})


class BackgroundSolver(object):
    def __init__(self, game):
        self.game = game
        thread = threading.Thread(target=self.run, args=())
        thread.daemon = True
        thread.start()

    def run(self):
        self.game = solve(self.game)
        # lockGamesFile()
        # games = loadGamesFile()
        new_game = getGameByID(self.game["_id"])
        new_game["words"] = self.game["words"]
        new_game["maxScore"] = self.game["maxScore"]
        new_game["maxWords"] = self.game["maxWords"]
        new_game["secondsToSolve"] = self.game["secondsToSolve"]
            
        if  new_game["maxWords"] == 0:
            new_game["percentFound"] = 100
        elif not "numWordsPlayersFound" in new_game:
            new_game["percentFound"] = 0
        else:
            new_game["percentFound"] = new_game["numWordsPlayersFound"] / new_game["maxWords"] * 100

        coll.update_one({"_id": new_game["_id"]}, {"$set": {"words": new_game["words"], "maxScore": new_game["maxScore"], "maxWords": new_game["maxWords"], "secondsToSolve": new_game["secondsToSolve"], "percentFound": new_game["percentFound"]}})

        # saveGamesFile(games)
        # unlockGamesFile()

def processAllTypedWords(game):
    if not "playerData" in game:
        game["playerData"] = {}
    if not "typedWords" in game:
        game["typedWords"] = {}
    for username in game["players"]:
        if username in game["typedWords"]:
            words = game["typedWords"][username]
        else:
            words = []
        
        if not username in game["players"]:
            game["players"].append(username)
        
        wordsDict = {}
        
        for word in words:
            if not word in wordsDict:
                if "words" in game: #if the board is already solved
                    if word in game["words"]: #check the list of solved words
                        wordsDict[word] = False #false means it's not a duplicate
                else: # if the board has not been solved yet
                    if isWordValid(game, word, wordList): #manually check using the board
                        wordsDict[word] = False #false means it's not a duplicate

        for player in game["playerData"]:
            playerData = game["playerData"][player]
            for word in wordsDict:
                if word in playerData["words"]:
                    wordsDict[word] = True #true means it is a duplicate
                    if not playerData["words"][word]:
                        playerData["words"][word] = True
                        playerData["score"] -= calculatePoints(word)
    
        score = 0
        for word in wordsDict:
            if not wordsDict[word]:
                score += calculatePoints(word)
        game["playerData"][username] = {
            "words": wordsDict,
            "score": score,
            "numWords": len(wordsDict)
        }

    winners = []
    winScore = -1
    playerWords = set([])
    dupes = []
    for player in game["playerData"]:
        playerData = game["playerData"][player]
        playerWords = playerWords.union(playerData["words"])
        playerScore = playerData["score"]
        if playerScore > winScore:
            winners = [player]
            winScore = playerScore
        elif playerScore == winScore and not player in winners:
            winners.append(player)
        for word in playerData["words"]:
            if playerData["words"][word] and not word in dupes:
                dupes.append(word)
    game["numWordsPlayersFound"] = len(playerWords)
    game["duplicates"] = len(dupes)
    if ("maxWords" not in game) or game["maxWords"] == 0:
        game["percentFound"] = 100
    else:
        game["percentFound"] = game["numWordsPlayersFound"] / game["maxWords"] * 100
    game["winners"] = winners
    game["winScore"] = winScore
    coll.update_one({"_id": game["_id"]}, {"$set": {"playerData": game["playerData"], "typedWords": game["typedWords"], "numWordsPlayersFound": game["numWordsPlayersFound"], "duplicates": game["duplicates"], "percentFound": game["percentFound"], "winners": game["winners"], "winScore": game["winScore"]}})
    return game

def updateGame(game):
    changed = False

    elapsedSinceCreatedSeconds = int(time.time()) - game["timeCreatedSeconds"]
    if "timeStartedSeconds" in game:
        elapsedSinceStartedSeconds = int(time.time()) - game["timeStartedSeconds"]
    else:
        elapsedSinceStartedSeconds = 0
    
    #check for stale games in the lobby
    if not game["isStarted"] and elapsedSinceCreatedSeconds > REMOVE_STALE_FROM_LOBBY_TIMEOUT:
        deleteGameByID(game["_id"])
        print("stale game #{} removed from lobby".format(game["_id"]))
        return None

    game["secondsLeft"] = game["minutes"]*60 - elapsedSinceStartedSeconds
    if game["secondsLeft"] <= -EXTRA_SECONDS_TO_SUBMIT and not game["isDone"]:
        game["isDone"] = True
        game = processAllTypedWords(game)
        changed = True
    # if the game has been over for longer than the archive timeout, and it's not already archived, and it's solved
    if game["secondsLeft"] <= -ARCHIVE_TIMEOUT and not game["isArchived"] and "words" in game:
        game["isArchived"] = True
        changed = True
    if changed:
        coll.update_one({"_id": game["_id"]}, {"$set": {"secondsLeft": game["secondsLeft"], "isDone": game["isDone"], "isArchived": game["isArchived"]}})
    return game

def toIntOrDefault(v, default):
    try:
        return int(v)
    except ValueError:
        return default

def toFloatOrDefault(v, default):
    try:
        return float(v)
    except ValueError:
        return default

def filterUsername(username):
    #only alphanumeric, max length is 32 chars
    return re.sub('[^a-zA-Z\d]', '', username)[:32]

def filterWord(word):
    #only letters, convert to lowercase
    return re.sub('[^a-z]', '', word.lower())

"""
This method doesn't return html, but JSON data for JS to digest.
It is called with AJAX requests, and the data will be formatted
to update part of the page without reloading the whole thing.
"""
def request_data(form):
    request = filterWord(form["request"])
    if request == "game":
        if "id" in form:
            id = toIntOrDefault(form["id"], -1)
            # lockGamesFile()
            # games = loadGamesFile()
            print("game request with id {}".format(id))
            game = getGameByID(id)
            if game is None:
                print("game not found")
                # unlockGamesFile()
                return json.dumps({})
            else:
                game = updateGame(game)
                if game is None:
                    return json.dumps({})
                print("game found")
                # if changed:
                #     saveGamesFile(games)
                # unlockGamesFile()
                return json.dumps({"game": game})
        else:
            print("game request with no id")
            return json.dumps({})
    if request == "games":
        # lockGamesFile()
        # games = loadGamesFile()
        # anyChanged = False
        games = coll.find()
        games = [updateGame(game) for game in games]
        games = [game for game in games if game] #remove entries that are "None"
        # for id in getAllIDs():
        #     updateGame(getGameByID(id))
            # if changed:
            #     anyChanged = True
        # if anyChanged:
        #     saveGamesFile(games)
        # unlockGamesFile()
        if "page" in form:
            page = filterWord(form["page"])
            if page == "lobby":
                games = [game for game in games if game["secondsLeft"] > -REMOVE_COMPLETED_FROM_LOBBY_TIMEOUT]
            elif page == "stats":
                games = [game for game in games if game["isArchived"]]
        return json.dumps({"games": games})
    if request == "basic" and "id" in form:
        id = toIntOrDefault(form["id"], -1)
        # lockGamesFile()
        # games = loadGamesFile()
        # unlockGamesFile()
        game = getGameByID(id)
        if game is not None:
            game = updateGame(game)
        if game is not None:
            return json.dumps({"isStarted": game["isStarted"], "players": game["players"]})
    if request == "savewords" and "id" in form and "words" in form and "username" in form:
        id = toIntOrDefault(form["id"], -1)
        words = form["words"].split(",")
        words = [filterWord(word) for word in words]
        username = filterUsername(form["username"])
        # lockGamesFile()
        # games = loadGamesFile()
        game = getGameByID(id)
        if game is not None:
            game = updateGame(game)
        if not "typedWords" in game:
            game["typedWords"] = {}
            changed = True
        typedWords = game["typedWords"]
        if not game["isDone"]:
            if not username in typedWords:
                typedWords[username] = []
                changed = True
            myTypedWords = typedWords[username]
            for word in words:
                if not word in myTypedWords:
                    myTypedWords.append(word)
                    changed = True
        if changed:
            updateAttr(game, "typedWords")
            # coll.update_one({"_id": game["_id"]}, {"$set": {"typedWords": typedWords})
            # saveGamesFile(games)
        # unlockGamesFile()
        return json.dumps({"typedWords": typedWords[username]})
    if request == "definition" and "word" in form:
        word = filterWord(form["word"])
        definitions = json.load(open(DEFINITIONS_FILE,'r'))
        return json.dumps({"definition": definitions[word]})
    if request == "invitation" and "id" in form:
        id = toIntOrDefault(form["id"], -1)
        toDelete = []
        for inv in invitations:
            newGame = getGameByID(invitations[inv])
            #If the new game is archived, the invitation is useless and can be removed from the list
            if newGame is None or newGame["isArchived"]:
                toDelete.append(inv)
        for inv in toDelete:
            del invitations[inv]
        print("invitations:", invitations)
        if id in invitations:
            invitedTo = invitations[id]
            return json.dumps({"invitation": invitedTo})

    return json.dumps({})

def do_action(form):
    # these are guaranteed by the function that calls this
    action = filterWord(form["action"])
    username = filterUsername(form["username"])

    if action == "create":
        if "preset" in form:
            preset = form["preset"]
            if preset == "5x5":
                size = 5
                letters = 4
                minutes = 3
            elif preset == "4x4":
                size = 4
                letters = 3
                minutes = 3
            elif preset == "random":
                size = random.randint(2,8)
                letters = [0,0,
                    random.randint(2,3), #2
                    random.randint(2,4), #3
                    random.randint(2,5), #4
                    random.randint(2,6), #5
                    random.randint(2,7), #6
                    random.randint(2,7), #7
                    random.randint(2,7)  #8
                ]
                letters = letters[size]
                minutes = random.randint(0,10)
                if minutes == 0: minutes = 0.5
            elif preset == "custom" and "size" in form and "letters" in form and "minutes" in form:
                size = form["size"]
                matched = re.match("^(\d+)x(\d+)$", size)
                if matched is None:
                    size = 5
                else:
                    size = int(matched.groups()[0])
                if size < 5:
                    lettersDefault = 3
                else:
                    lettersDefault = 4
                letters = toIntOrDefault(form["letters"], lettersDefault)
                minutes = toFloatOrDefault(form["minutes"], 3)
            else:
                return "lobby", None
            # lockGamesFile()
            # games = loadGamesFile()
            print("creating game: size={}, letters={}, minutes={}".format(size, letters, minutes))
            game = create(size=size, letters=letters, minutes=minutes)
            game["_id"] = newGameID()
            BackgroundSolver(game)
            game["players"].append(username)
            print(game)
            coll.insert_one(game)
            # games.append(game)
            # saveGamesFile(games)
            # unlockGamesFile()
            if "inviteFrom" in form:
                inviteFrom = toIntOrDefault(form["inviteFrom"], -1)
                if inviteFrom >= 0:
                    invitations[inviteFrom] = game["_id"]
                print("invitations:", invitations)
            return "pregame", game["_id"]
        return "lobby", None

    if action == "join" and "id" in form:
        id = toIntOrDefault(form["id"], -1)
        # lockGamesFile()
        # games = loadGamesFile()
        game = getGameByID(id)
        if game is None:
            # unlockGamesFile()
            return "lobby", None
        # can't join after the game is finished
        if game["isDone"]:
            # unlockGamesFile()
            return "view", id
        elif not username in game["players"]:
            game["players"].append(username)
            updateAttr(game, "players")
            # coll.update_one({"_id": game["_id"]}, {"$set": {"players": game["players"]})
            # saveGamesFile(games)
        # unlockGamesFile()
        if game["isStarted"]:
            return "play", id
        else:
            return "pregame", id

    if action == "start" and "id" in form:
        id = toIntOrDefault(form["id"], -1)
        # lockGamesFile()
        # games = loadGamesFile()
        game = getGameByID(id)
        if game is None:
            # unlockGamesFile()
            return "lobby", None
        players = game["players"]
        if len(players) > 0 and players[0] == username:
            # player is the host, start the game
            if not game["isStarted"]:
                game["isStarted"] = True
                game["timeStartedSeconds"] = int(time.time())
                coll.update_one({"_id": game["_id"]}, {"$set": {"isStarted": game["isStarted"], "timeStartedSeconds": game["timeStartedSeconds"]}})
                # saveGamesFile(games)
        # unlockGamesFile()
        if not game["isStarted"]:
            return "pregame", id
        elif not game["isDone"]:
            return "play", id
        else:
            return "view", id

    if action == "cancel" and "id" in form:
        id = toIntOrDefault(form["id"], -1)
        # lockGamesFile()
        # games = loadGamesFile()
        game = getGameByID(id)
        # works only in the pregame and play phases (i.e. isDone = False)
        if game is not None and not game["isDone"]:
            # remove this player from the game, promoting the next player to host.
            game["players"].remove(username)
            # if there are no more players, delete the game
            if len(game["players"]) == 0:
                games = deleteGameByID(id)
            else:
                updateAttr(game, "players")
            # saveGamesFile(games)
        # unlockGamesFile()
        return "lobby", None
    return "lobby", None

def load_page(form, page=None, id=None):
    if page is None:
        if "page" in form:
            page = filterWord(form["page"])
        else:
            page = "lobby"
    if not "username" in form and not page in ("stats", "json", "view"):
        page = "login"

    if id is None and "id" in form:
        id = toIntOrDefault(form["id"], -1)
    
    if "prev" in form:
        prev = filterWord(form["prev"])
    else:
        prev = "lobby"

    kwargs = {
        "nav": nav,
        "active": "boggle",
        "stylesheet": "boggle",
        "formMethod": "get",
        "id": id
    }

    if page == "login":
        return render_template("boggle/login.html", page=page, **kwargs)

    if "username" in form:
        username = filterUsername(form["username"])
    else:
        username = ""

    kwargs["username"] = username

    if page == "pregame" and id is not None:
        return render_template("boggle/pregame.html", **kwargs)

    if page == "play" and id is not None:
        return render_template("boggle/play.html", **kwargs)

    if page == "view" and id is not None:
        return render_template("boggle/view.html", prev=prev, **kwargs)

    if page == "stats":
        return render_template("boggle/stats.html", prev=prev, **kwargs)

    if page == "json":
        return json.dumps([x for x in coll.find()], indent=2)

    if page == "lobby":
        return render_template("boggle/lobby.html", remove_completed_from_lobby_timeout=REMOVE_COMPLETED_FROM_LOBBY_TIMEOUT, **kwargs)

    return "error with page '" + str(page) + "'"


"""
This method processes all requests coming in, and passes
them to the correct function.

There are 3 important fields:
action - an action to be taken before loading the page,
    such as leaving a game or submitting a list of words
page - the page to be returned, such as the login, lobby,
    pregame, play, and stats pages
request - ask for a certain type of data, such as current
    games, past games, data on 1 particular game, or word
    definition. This overrides the page, so if a request,
    page, and action are all specified, the server will
    do the action, then return the requested data,
    ignoring the page variable.
"""
def app(form):
    page = None
    id = None
    if "action" in form and "username" in form:
        page, id = do_action(form)
    
    if "request" in form:
        return request_data(form)
    else:
        return load_page(form, page, id)
