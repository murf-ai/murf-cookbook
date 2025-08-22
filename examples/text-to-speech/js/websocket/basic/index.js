const WS_URL = "wss://api.murf.ai/v1/speech/stream-input";
const SAMPLE_RATE = 44100;

let socket = null;
let audioChunks = []; // Store raw audio chunks
let base64AudioChunks = []; // Stored base64 audio chunks
let audioContext;
let playheadTime;
let isPlaying = false;
let wavHeaderSet = true;

const connectBtn = document.getElementById("connectBtn");
const disconnectBtn = document.getElementById("disconnectBtn");
const sendBtn = document.getElementById("sendBtn");
const messageBox = document.getElementById("messageBox");
const log = document.getElementById("log");
const clearBtn = document.getElementById("clearBtn");
const apiKey = document.getElementById("apiKey");

function logMessage(message) {
  log.textContent += message + "\n";
  log.scrollTop = log.scrollHeight;
}

function getPayload(msg) {
  const message = msg?.trim() || messageBox.value.trim();

  const payload = {
    voice_config: {
      voiceId: document.getElementById("voiceId")?.value || "en-US-daniel",
      style: document.getElementById("voiceStyle")?.value || "Conversational",
      rate: Number(document.getElementById("rate")?.value) || 0,
      pitch: Number(document.getElementById("pitch")?.value) || 0,
      multiNativeLocale:
        document.getElementById("multiNativeLocale")?.value || "en-US",
      sampleRate: 44100,
      format: "WAV",
      channelType: "MONO",
      // pronunciationDictionary: {
      //   guess: { type: 'IPA', pronunciation: 'laɪv' },
      // },
      encodeAsBase64: false,
      variation: 5,
    },
    context_id: "SAMPLE_CONTEXT_ID",
    text: message,
  };

  return payload;
}

connectBtn.onclick = () => {
  logMessage("🔗 Connecting to WebSocket...");
  socket = new WebSocket(WS_URL + `?api-key=${apiKey.value}`);
  audioContext = new (window.AudioContext || window.webkitAudioContext)();
  playheadTime = audioContext.currentTime; // Initialize playhead time
  socket.onopen = () => {
    logMessage("✅ WebSocket connected");
    connectBtn.disabled = true;
    disconnectBtn.disabled = false;
    sendBtn.disabled = false;
  };

  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (!data.audio) {
        console.log(data);
      }

      if (data.audio) {
        playAudioChunk(data.audio);
      }
      if (data.requestId) {
        logMessage("📥 Request ID: " + data.requestId);
      }
      if (data.isFinalAudio) {
        logMessage("📥 Final audio chunk received");
        playSavedChunks();
      }
    } catch (err) {
      console.error("Error parsing JSON:", err);
      logMessage("⚠️ Non-JSON message: " + event.data);
    }
  };

  socket.onclose = () => {
    logMessage("❌ WebSocket disconnected");
    connectBtn.disabled = false;
    disconnectBtn.disabled = true;
    sendBtn.disabled = true;
  };

  socket.onerror = (err) => {
    logMessage("❌ WebSocket error: " + JSON.stringify(err));
  };
};

disconnectBtn.onclick = () => {
  if (socket) {
    socket.close();
  }
};

apiKey.oninput = (e) => {
  const apiKeyValue = e.target.value;
  if (apiKeyValue?.trim()?.length > 0) {
    connectBtn.disabled = false;
  } else {
    connectBtn.disabled = true;
    sendBtn.disabled = true;
  }
};

sendBtn.onclick = () => {
  const payload = getPayload();
  const message = payload?.text;
  if (message && socket && socket.readyState === WebSocket.OPEN) {
    socket.send(
      JSON.stringify({
        voice_config: payload.voice_config,
        context_id: payload.context_id,
      })
    );
    logMessage(
      "📤 Sent: " +
        JSON.stringify({
          voice_config: payload.voice_config,
          context_id: payload.context_id,
        })
    );
    socket.send(
      JSON.stringify({
        text: payload.text,
        context_id: payload.context_id,
      })
    );
    logMessage(
      "📤 Sent: " +
        JSON.stringify({
          text: payload.text,
          context_id: payload.context_id,
        })
    );

    playheadTime = audioContext.currentTime; // Reset playhead time
    audioChunks = []; // Reset audio chunks
    isPlaying = false; // Reset playhead
    wavHeaderSet = true; // Reset WAV header flag
    base64AudioChunks = [];
    const audio = document.getElementById("audioPlayer");
    if (audio) {
      audio.src = ""; // Reset audio source
    }
  }
};

clearBtn.onclick = () => {
  log.textContent = "";
};

function toggleAccordion(id) {
  const content = document.getElementById(id);
  content.classList.toggle("hidden");
}

function base64ToPCMFloat32(base64) {
  let binary = atob(base64);
  const offset = wavHeaderSet ? 44 : 0; // Skip WAV header if present
  if (wavHeaderSet) {
    console.log("wavHeader", binary.substring(0, 44));
  }
  wavHeaderSet = false;
  const length = binary.length - offset;

  const buffer = new ArrayBuffer(length);
  const byteArray = new Uint8Array(buffer);
  for (let i = 0; i < byteArray.length; i++) {
    byteArray[i] = binary.charCodeAt(i + offset);
  }

  const view = new DataView(byteArray.buffer);
  const sampleCount = byteArray.length / 2;
  const float32Array = new Float32Array(sampleCount);

  for (let i = 0; i < sampleCount; i++) {
    const int16 = view.getInt16(i * 2, true);
    float32Array[i] = int16 / 32768;
  }

  return float32Array;
}

function chunkPlay() {
  if (audioChunks.length > 0) {
    const chunk = audioChunks.shift();
    if (audioContext.state === "suspended") {
      audioContext.resume();
    }
    const buffer = audioContext.createBuffer(1, chunk.length, SAMPLE_RATE);
    buffer.copyToChannel(chunk, 0);
    const source = audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(audioContext.destination);
    const now = audioContext.currentTime;
    if (playheadTime < now) {
      playheadTime = now + 0.05; // Add a small delay
    }
    source.start(playheadTime);
    playheadTime += buffer.duration;

    if (audioChunks.length > 0) {
      chunkPlay();
    } else {
      isPlaying = false;
    }
  }
}

function playAudioChunk(base64Audio) {
  try {
    const float32Array = base64ToPCMFloat32(base64Audio);
    if (!float32Array) {
      return;
    }

    const frameCount = float32Array.length;

    audioChunks.push(float32Array);
    base64AudioChunks.push(base64Audio);

    if (playheadTime > 1 && !isPlaying) {
      isPlaying = true;
      audioContext.resume(); // Resume audio context if suspended
      chunkPlay();
    }
  } catch (error) {
    console.error("Error playing chunk", error);
  }
}

// ------------------ WAV Header -----------------
function base64ToUint8Array(base64) {
  const binary = atob(base64);
  const len = binary.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function createWavHeader(
  dataLength,
  sampleRate = SAMPLE_RATE,
  numChannels = 1,
  bitDepth = 16
) {
  const blockAlign = (numChannels * bitDepth) / 8;
  const byteRate = sampleRate * blockAlign;
  const buffer = new ArrayBuffer(44);
  const view = new DataView(buffer);

  function writeStr(offset, str) {
    for (let i = 0; i < str.length; i++)
      view.setUint8(offset + i, str.charCodeAt(i));
  }

  writeStr(0, "RIFF");
  view.setUint32(4, 36 + dataLength, true); // total file size - 8
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true); // PCM format
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitDepth, true);
  writeStr(36, "data");
  view.setUint32(40, dataLength, true);

  return new Uint8Array(buffer);
}

function playCombinedWavChunks(base64Chunks) {
  const pcmData = [];

  for (let i = 0; i < base64Chunks.length; i++) {
    const bytes = base64ToUint8Array(base64Chunks[i]);

    if (i === 0) {
      pcmData.push(bytes.slice(44)); // skip header in first chunk
    } else {
      pcmData.push(bytes); // entire chunk is raw PCM
    }
  }

  // Combine all PCM chunks
  const totalPcm = new Uint8Array(
    pcmData.reduce((sum, c) => sum + c.length, 0)
  );
  let offset = 0;
  for (const part of pcmData) {
    totalPcm.set(part, offset);
    offset += part.length;
  }

  const wavHeader = createWavHeader(totalPcm.length);
  console.log("wavHeader final", wavHeader);
  const finalWav = new Uint8Array(wavHeader.length + totalPcm.length);
  finalWav.set(wavHeader, 0);
  finalWav.set(totalPcm, wavHeader.length);

  const blob = new Blob([finalWav], { type: "audio/wav" });
  const url = URL.createObjectURL(blob);

  const audio = document.getElementById("audioPlayer");
  audio.src = url;
}

// --------------------- END WAV Header -----------------

function playSavedChunks() {
  const savedChunks = base64AudioChunks;
  if (savedChunks && savedChunks.length > 0) {
    playCombinedWavChunks(savedChunks);
  }
}
