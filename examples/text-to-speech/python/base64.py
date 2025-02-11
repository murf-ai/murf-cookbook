from murf import Murf

def generate_base64(text: str, voice_id: str):
    client = Murf()
    res = client.text_to_speech.generate(
        text=text, 
        voice_id=voice_id, 
        encode_as_base_64=True,
        request_options={
            'additional_headers': {
                'accept-encoding': 'gzip'
            }
        }
    )
    return res.encoded_audio

if __name__ == "__main__":
    generate_base64(
        text="Hello, World!",
        voice_id="en-US-natalie"
    )