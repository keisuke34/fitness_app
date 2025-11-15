// static/stopwatch.js
// 共通ストップウォッチ（全ページ共通）
// ・.stopwatch-container ごとに1つのタイマーを持つ
// ・カウントアップ / カウントダウン対応
// ・カウントダウン時 10〜0 で WAV 音声再生
// ・0 まではマイナス表示（-00:00:05 → … → -00:00:00）
// ・0 のあと 00:00:01, 00:00:02 … とカウントアップ
// ・必要なら .stopwatch-seconds-input に合計秒数を反映してフォーム送信に使える

(function () {
  // ==============================
  // 10〜0 の WAV 音声の準備
  // ==============================
  const countdownVoices = {};
  const voiceBasePath = "/static/sounds/";
  const voiceFiles = {
    10: "female_10.wav",
    9:  "female_09.wav",
    8:  "female_08.wav",
    7:  "female_07.wav",
    6:  "female_06.wav",
    5:  "female_05.wav",
    4:  "female_04.wav",
    3:  "female_03.wav",
    2:  "female_02.wav",
    1:  "female_01.wav",
    0:  "female_00.wav"
  };

  function loadVoices() {
    Object.keys(voiceFiles).forEach((key) => {
      const sec = Number(key);
      const audio = new Audio(voiceBasePath + voiceFiles[sec]);
      audio.preload = "auto";
      countdownVoices[sec] = audio;
    });
  }

  function playVoiceForSecond(sec) {
    const audio = countdownVoices[sec];
    if (!audio) return;
    try {
      audio.currentTime = 0;
      audio.play().catch(() => {
        // 自動再生ブロックなどは無視
      });
    } catch (e) {
      // エラーは無視
    }
  }

  // ==============================
  // 表示フォーマット関数
  // ==============================
  function pad2(n) {
    return n.toString().padStart(2, "0");
  }

  function formatTime(totalSeconds, negative) {
    const neg = negative === true;
    let s = Math.abs(totalSeconds);

    const h = Math.floor(s / 3600);
    s -= h * 3600;
    const m = Math.floor(s / 60);
    const sec = s % 60;

    const text = `${pad2(h)}:${pad2(m)}:${pad2(sec)}`;
    return neg ? `-${text}` : text;
  }

  // ==============================
  // 各コンテナごとの初期化
  // ==============================
  function initStopwatch(container) {
    const display = container.querySelector(".stopwatch-display");
    const countdownToggle = container.querySelector(".stopwatch-countdown-toggle");
    const countdownSecondsInput = container.querySelector(".stopwatch-countdown-seconds");
    const startBtn = container.querySelector(".stopwatch-start");
    const stopBtn = container.querySelector(".stopwatch-stop");
    const resetBtn = container.querySelector(".stopwatch-reset");
    const secondsHidden = container.querySelector(".stopwatch-seconds-input");

    if (!display || !startBtn || !stopBtn || !resetBtn) {
      // 必要な要素が揃っていなければ何もしない
      return;
    }

    let mainTimerId = null;      // カウントアップ用
    let countdownTimerId = null; // カウントダウン用
    let running = false;
    let inCountdown = false;

    let elapsedSeconds = 0;      // カウントアップ中に増える
    let countdownRemaining = 0;  // カウントダウン中に減る

    function updateDisplayUp() {
      display.textContent = formatTime(elapsedSeconds, false);
      if (secondsHidden) {
        secondsHidden.value = elapsedSeconds;
      }
    }

    function updateDisplayDown(sec) {
      display.textContent = formatTime(sec, true); // マイナス表示
      if (secondsHidden) {
        secondsHidden.value = 0; // カウントダウン中は 0 のまま
      }
    }

    function clearMainTimer() {
      if (mainTimerId !== null) {
        clearInterval(mainTimerId);
        mainTimerId = null;
      }
    }

    function clearCountdownTimer() {
      if (countdownTimerId !== null) {
        clearInterval(countdownTimerId);
        countdownTimerId = null;
      }
    }

    function resetAll() {
      clearMainTimer();
      clearCountdownTimer();
      running = false;
      inCountdown = false;
      elapsedSeconds = 0;
      countdownRemaining = 0;
      display.textContent = "00:00:00";
      if (secondsHidden) {
        secondsHidden.value = 0;
      }
    }

    function startMainTimer() {
      clearMainTimer();
      running = true;
      mainTimerId = setInterval(() => {
        elapsedSeconds += 1;
        updateDisplayUp();
      }, 1000);
      updateDisplayUp();
    }

    function startCountdownThenUp() {
      if (!countdownSecondsInput) {
        // カウントダウン入力がなければ、いきなりカウントアップ
        startMainTimer();
        return;
      }

      let cd = parseInt(countdownSecondsInput.value || "0", 10);
      if (cd > 10) cd = 10;
      if (cd < 1) {
        // 0以下ならカウントダウンなしでカウントアップ
        startMainTimer();
        return;
      }

      clearCountdownTimer();
      inCountdown = true;
      countdownRemaining = cd;

      // 最初の秒数を表示＆音声再生
      updateDisplayDown(countdownRemaining);
      playVoiceForSecond(countdownRemaining);

      countdownTimerId = setInterval(() => {
        countdownRemaining -= 1;

        if (countdownRemaining >= 0) {
          // 0 〜 cd の間、マイナス表示＋音声
          updateDisplayDown(countdownRemaining);
          playVoiceForSecond(countdownRemaining);
        }

        if (countdownRemaining <= 0) {
          // 0 を再生し終わったら、カウントアップ開始
          clearCountdownTimer();
          inCountdown = false;
          elapsedSeconds = 0;
          updateDisplayUp();
          startMainTimer();
        }
      }, 1000);
    }

    // --------------------------
    // イベントハンドラ
    // --------------------------
    startBtn.addEventListener("click", () => {
      if (running || inCountdown) return;

      const useCountdown = countdownToggle && countdownToggle.checked;
      if (useCountdown) {
        startCountdownThenUp();
      } else {
        startMainTimer();
      }
    });

    stopBtn.addEventListener("click", () => {
      if (inCountdown) {
        clearCountdownTimer();
        inCountdown = false;
      }
      if (running) {
        clearMainTimer();
        running = false;
      }
    });

    resetBtn.addEventListener("click", () => {
      resetAll();
    });

    // 初期表示
    resetAll();
  }

  // ==============================
  // ページ読み込み時に全コンテナ初期化
  // ==============================
  document.addEventListener("DOMContentLoaded", () => {
    loadVoices();
    document.querySelectorAll(".stopwatch-container").forEach((container) => {
      initStopwatch(container);
    });
  });
})();
