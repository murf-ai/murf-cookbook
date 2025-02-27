# This example demonstrates how to concatenate multiple audio files using ffmpeg.
# Make sure ffmpeg is installed on your system

import subprocess
import requests
import os
from murf import Murf

def generate_audio_files(client: Murf, texts, voice_id):
    audio_files = []
    for i, text in enumerate(texts):
        res = client.text_to_speech.generate(text=text, voice_id=voice_id, format='MP3')
        audio_url = res.audio_file
        audio_content = requests.get(audio_url).content
        file_path = f'audio_{i}.mp3'
        with open(file_path, 'wb') as audio_f:
            audio_f.write(audio_content)
        audio_files.append(file_path)
    return audio_files

def create_file_list(audio_files, list_file_path):
    with open(list_file_path, 'w') as f:
        for file_path in audio_files:
            f.write(f"file '{file_path}'\n")

def stitch_audio_files(list_file_path, output_file):
    command = [
        'ffmpeg',
        '-f', 'concat',
        '-safe', '0',
        '-i', list_file_path,
        '-c', 'copy',
        output_file
    ]
    subprocess.run(command, check=True)

def clean_up_files(file_paths):
    for file_path in file_paths:
        os.remove(file_path)

def main(texts, voice_id):
    client = Murf(api_key="YOUR_API_KEY")
    
    audio_files = generate_audio_files(client, texts, voice_id)
    list_file_path = 'audio_files.txt'
    output_file = 'output_audio.mp3'
    
    create_file_list(audio_files, list_file_path)
    stitch_audio_files(list_file_path, output_file)
    clean_up_files(audio_files + [list_file_path])

if __name__ == "__main__":
    main(
        texts=["Hello, World!", "My name is natalie", "This is a test."],
        voice_id="en-US-natalie"
    )