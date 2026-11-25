import os
import re
import time
from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from google import genai

app = Flask(__name__)

# 從環境變數讀取金鑰
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)


def translate_text(text: str) -> str:
    """使用 Gemini 進行繁體中文與印尼文雙向翻譯（含 503 塞車自動重試與備援模型）"""
    prompt = f"""
你是一位精通台灣繁體中文與印尼日常口語的專業雙向翻譯員。
請判斷以下輸入文字的語言並執行翻譯：
1. 如果輸入是「中文」（繁體或簡體），請翻譯成自然、禮貌且道地的「印尼文 (Bahasa Indonesia)」。
2. 如果輸入是「印尼文」（包含常見的通訊軟體縮寫，如 yg, gak, gk, sy, km, tdk, sdh, blm, bsk, makasih 等），請翻譯成自然流暢的「台灣繁體中文」。
3. 嚴格限制：只需直接輸出翻譯後的結果，絕對不要包含任何解釋、拼音、問候語或額外標點符號。

輸入文字：
{text}
"""
    # 依序嘗試主力模型與輕量備援模型，避免單一模型瞬間塞車
    models_to_try = ['gemini-3.8-flash', 'gemini-3.8-flash', 'gemini-3.8-pro']

    for model_name in models_to_try:
        try:
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            return response.text.strip()
        except Exception as e:
            print(f"模型 {model_name} 發生錯誤: {e}")
            time.sleep(1)  # 稍等 1 秒後自動切換下一個模型重試

    return "⚠️ 翻譯服務暫時忙碌中，請稍後再試。"


@app.route("/", methods=['GET'])
def home():
    return "LINE Chinese-Indonesian Translator Bot is running!"


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text.strip()

    # 過濾掉純數字、純符號或單純網址，避免無意義翻譯
    if not user_text or re.match(r'^[\d\s\W]+$', user_text) or user_text.startswith('http'):
        return

    # 執行翻譯
    translated_result = translate_text(user_text)

    # 使用 Reply API 回覆（免費無上限）
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=translated_result)]
            )
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
