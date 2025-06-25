"""
This example shows how to stream audio from the Murf API and play it with pydub. 
The entire audio is downloaded and then played back.

To run this example, you need to have the following installed:
- murf
- pydub
"""

from murf import Murf
from pydub import AudioSegment
from pydub.playback import play
import io

MURF_API_KEY = "YOUR_API_KEY"
VOICE_ID = "en-US-maverick"

TEXT_TO_SYNTHESIZE = (
    "Hi, how can I help you this fine day? "
    "This is a slightly longer sentence to demonstrate streaming capabilities. "
    "We can add even more text here to make it larger, simulating a paragraph or "
    "a document that needs to be synthesized and played back in a streaming fashion "
    "for a better user experience. Let's imagine this is a significant portion of a chapter from a book, "
    "or a lengthy article being converted to audio."
)

def main():
    """
    Main function to synthesize speech using Murf API and play it with pydub.
    """
    print("Initializing Murf client...")
    try:
        client = Murf(api_key=MURF_API_KEY)
    except Exception as e:
        print(f"Failed to initialize Murf client: {e}")
        return

    print(f"Starting speech synthesis for text: '{TEXT_TO_SYNTHESIZE[:70]}...'")

    try:
        # The stream method is expected to return an iterable of audio chunks (bytes).
        audio_stream_iterator = client.text_to_speech.stream(
            text=TEXT_TO_SYNTHESIZE,
            voice_id=VOICE_ID,
            format="WAV"  # pydub can handle MP3. WAV is also an option.
        )

        # Accumulate the audio data from the stream
        print("Receiving audio stream...")
        audio_data_chunks = []
        for chunk in audio_stream_iterator:
            audio_data_chunks.append(chunk)
        
        audio_data = b"".join(audio_data_chunks)

        if not audio_data:
            print("No audio data received from the stream. Please check your API key, voice ID, and text.")
            return

        print(f"Speech synthesis complete. Received {len(audio_data)} bytes of audio data.")

        print("Loading audio data into pydub AudioSegment...")
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_data), format="wav")

        print("Playing audio...")
        play(audio_segment)
        print("Audio playback finished.")

    except Exception as e:
        print(f"An error occurred during synthesis or playback: {e}")

if __name__ == "__main__":
    main()
