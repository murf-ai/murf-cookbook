# This example demonstrates how to concatenate multiple audio files using pydub
# pip install pydub

import io
import requests
from pydub import AudioSegment
from murf import Murf

def generate_audio_files(client: Murf, texts, voice_id, file_format):
    audio_segments = []
    for text in texts:
        res = client.text_to_speech.generate(text=text, voice_id=voice_id, format=file_format.upper())
        audio_url = res.audio_file
        audio_content = requests.get(audio_url).content
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_content), format=file_format.lower())
        audio_segments.append(audio_segment)
    return audio_segments

def concatenate_audio_files(audio_segments, output_file, file_format):
    combined = AudioSegment.empty()
    for audio in audio_segments:
        combined += audio
    combined.export(output_file, format=file_format)

def main(texts, voice_id, output_file, file_format):
    client = Murf()
    
    audio_segments = generate_audio_files(client, texts, voice_id, file_format)
    
    concatenate_audio_files(audio_segments, output_file, file_format)

if __name__ == "__main__":
    main(
        texts=["Hello, World!", "My name is natalie", "Always a pleasure to meet you all!"],
        voice_id="en-US-natalie",
        output_file="output_audio.wav",
        file_format="wav"
    )