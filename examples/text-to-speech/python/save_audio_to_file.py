from murf import Murf
import requests

def save_to_file(text: str, voice_id: str, file_path: str):
    client = Murf(api_key="YOUR_API_KEY")
    
    res = client.text_to_speech.generate(
        text=text, 
        voice_id=voice_id
    )
    url_to_audio_file = res.audio_file
    audio_file = requests.get(url_to_audio_file)
    
    with open(file_path, 'wb') as file:
        file.write(audio_file.content)

if __name__ == '__main__':
    save_to_file("Hello, World!", "en-US-natalie", "hello_world.wav")