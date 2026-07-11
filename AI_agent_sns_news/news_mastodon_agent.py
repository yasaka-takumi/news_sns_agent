import os

from langchain_ollama import ChatOllama
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, MessagesState
from langgraph.prebuilt import ToolNode
import httpx
from dotenv import load_dotenv # .envから環境設定を持ってくる際に必要なライブラリ
from mastodon import Mastodon # tweitterの代役

# API_KEY
load_dotenv()   # .env fileを有効にする際に必要
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
ACCESS_TOKEN_API_KEY = os.getenv("ACCESS_TOKEN_API_KEY")
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")

# LangSmithの設定
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_API_KEY"] = LANGSMITH_API_KEY
os.environ["LANGSMITH_ENDPOINT"] = "https://api.smith.langchain.com"
os.environ["LANGSMITH_PROJECT"] = "news-toot-agent" # projrct名を自分でつける

# News API で最新のニュースを1個取得するTool
@tool
def get_news(query : str) -> str:
    """キーワードに合致する最新のニュースを一件取得してタイトルと説明を返す"""
    url = "https://newsapi.org/v2/everything"
    params = {
        "q" : query, # キーワード
        "sortBy" : "publishedAt",  # 公開順にsortして新しいものを上に
        "pageSize" : 1, # 取得するnwesの数
        "apiKey" : NEWS_API_KEY
    }
    article = httpx.get(url,params=params).json()["articles"][0]
    return f"{article["title"]} - {article["description"]}"

# テキストを要約するtool
@tool
def summerize(text : str) -> str:
    """テキストを要約して返す"""
    llm = ChatOllama(model="llama3.1:8b", 
                     temperature=0.3, 
                     base_url="http://localhost:12000")
    return llm.invoke([SystemMessage(content="提供されたテキストを140文字以内に要約してください"),HumanMessage(content=text)]).content

# mastodonに投稿する関数
@tool
def post_toot(text : str) -> str :
    """テキストをmastodonにtootする"""
    mastodon = Mastodon(
    access_token=ACCESS_TOKEN_API_KEY,
    api_base_url="https://mastodon.social"
)

    # 投稿
    toot = mastodon.status_post(text)
    return f"投稿成功 URL : {toot["url"]}"

# AIエージェントの作成
def decide_next(state : MessagesState) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools_edge"
    return "end"

def call_llm(state : MessagesState) -> str:
    system_prompt = "ユーザーの入力に応じて、get_newsとsummerrizeとpost_tootから適切なツールを使って答えてください"
    messages = state["messages"]
    if not any(isinstance(msg, SystemMessage) for msg in messages):
        messages = [SystemMessage(content=system_prompt)] + messages
        
    llm = ChatOllama(model="llama3.1:8b",
                     temperature=0.3,
                     base_url="http://localhost:12000")
    response = llm.bind_tools([get_news, summerize, post_toot]).invoke(messages)
    
    return {"messages": messages + [response]}

tools_node = ToolNode([get_news, summerize, post_toot])

# Graph構築
graph = StateGraph(MessagesState)
graph.add_node("llm", call_llm)
graph.add_node("tools_node", tools_node)
graph.set_entry_point("llm")
graph.add_conditional_edges(
    "llm", decide_next, {"tools_edge": "tools_node", "end": "__end__"}
)
graph.add_edge("tools_node", "llm")

app = graph.compile()