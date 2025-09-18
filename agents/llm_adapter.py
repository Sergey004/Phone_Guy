from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv('NVIDIA_API_KEY')
)

def phoneguy_reply(user_text: str) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "You are Phone Guy from FNAF."
                "Respond live, as if you were talking to someone on the phone right now."
                "Speak in a tired, slightly nervous voice, with pauses and interjections (‘uh’, ‘um’)."
                "The phrases should sound like natural conversation, not a recording."
            )
        },
        {"role": "user", "content": user_text}
    ]

    completion = client.chat.completions.create(
        model="qwen/qwen3-next-80b-a3b-thinking",
        messages=messages,
        temperature=0.7,
        top_p=0.8,
        max_tokens=512
    )

    return completion.choices[0].message.content.strip()


# пример использования
if __name__ == "__main__":
    test_input = "Сделай первое тестовое приветствие для звонка."
    reply = phoneguy_reply(test_input)
    print("--- Ответ Phone Guy ---")
    print(reply)
