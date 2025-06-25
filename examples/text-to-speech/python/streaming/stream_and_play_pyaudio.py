"""
This example shows how to stream audio from the Murf API and play it with pyaudio.
The audio is streamed and played back as it arrives.

To run this example, you need to have the following installed:
- murf
- pyaudio
- httpx
- struct
"""
import httpx, pyaudio, struct

API_KEY   = "YOUR_API_KEY"
VOICE_ID  = "en-US-amara"
STREAM_URL = "https://api.murf.ai/v1/speech/stream"

def stream_audio(text: str, voice_id: str = VOICE_ID):
    """Stream TTS audio from the Murf API.

    This is a generator that first yields a tuple with the
    audio format information ``(channels, sample_rate, sampwidth)``
    followed by chunks of raw PCM bytes.

    The caller can use the first yielded item to configure the
    playback device (or any other consumer) and then feed the
    subsequent PCM chunks into it.
    """
    headers = {"api-key": API_KEY}
    body    = {
        "text": text,
        "voice_id": voice_id,
        "format": "WAV",
    }

    # Open the HTTP streaming response for the entire lifetime of the
    # generator so that audio can be consumed lazily by the caller.
    with httpx.stream("POST", STREAM_URL, json=body,
                      headers=headers, timeout=None) as resp:
        resp.raise_for_status()
        chunks = resp.iter_bytes()

        # ---------------- Parse WAV header -----------------------------
        header       = bytearray()
        data_offset  = None
        for chunk in chunks:
            header.extend(chunk)
            pos = header.find(b'data')
            if pos != -1 and len(header) >= pos + 8:
                # Found the ``data`` sub-chunk; the real PCM starts 8 bytes after
                data_offset = pos + 8
                break

        if data_offset is None:
            raise RuntimeError("Malformed WAV stream: no 'data' chunk found")

        # Extract format info from the ``fmt `` sub-chunk
        channels        = struct.unpack_from('<H', header, 22)[0]
        sample_rate     = struct.unpack_from('<I', header, 24)[0]
        bits_per_sample = struct.unpack_from('<H', header, 34)[0]
        sampwidth       = bits_per_sample // 8

        # Expose format information to the caller
        yield (channels, sample_rate, sampwidth)

        # Yield any PCM data that was already contained in *header*
        if data_offset < len(header):
            yield header[data_offset:]

        # Yield the rest of the PCM data as it arrives
        for chunk in chunks:
            if chunk:
                yield chunk


# ----------------------------------------------------------------------

def play_audio(pcm_stream):
    """Play raw PCM bytes coming from *pcm_stream* using PyAudio.

    The *pcm_stream* must be the generator returned by ``stream_audio``.
    """
    # The first item provides the audio parameters we need to configure
    # PortAudio.
    channels, sample_rate, sampwidth = next(pcm_stream)

    pa = pyaudio.PyAudio()
    out = pa.open(
        format = pa.get_format_from_width(sampwidth),
        channels = channels,
        rate = sample_rate,
        output = True,
        frames_per_buffer = 2048,
    )

    frame_size = sampwidth * channels
    pending = bytearray()

    for chunk in pcm_stream:
        if not chunk:
            continue
        pending.extend(chunk)
        # Write only complete frames to keep the stream aligned.
        n_full_bytes = len(pending) - (len(pending) % frame_size)
        if n_full_bytes:
            out.write(bytes(pending[:n_full_bytes]))
            del pending[:n_full_bytes]

    # Flush any remaining (already frame-aligned) data.
    if pending:
        out.write(bytes(pending))

    out.stop_stream()
    out.close()
    pa.terminate()

def stream_and_play(text: str, voice_id: str = VOICE_ID) -> None:
    play_audio(stream_audio(text, voice_id))


if __name__ == "__main__":
    paragraph = (
        "Hi, how can I help you this fine day? "
        "This is a slightly longer sentence to demonstrate streaming capabilities. "
        "We can add even more text here to make it larger, simulating a paragraph or "
        "a document that needs to be synthesized and played back in a streaming fashion. "
        "Let's imagine this is a significant portion of a chapter from a book."
    )
    stream_and_play(paragraph)

