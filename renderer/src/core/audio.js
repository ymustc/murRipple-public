/**
 * 分轨音频层。分轨数由 timeline 顶层的 stems 字段声明——真歌四条，
 * 合成曲九条，这一层不写死数量。
 *
 * 全部走 decodeAudioData 而不用 <audio> 标签：产物要支持双击本地打开，
 * 而 file:// 下 fetch 被 CORS 拦、createMediaElementSource 会因跨域污染
 * 而静音，只有 base64 → ArrayBuffer → decodeAudioData 这条路走得通。
 *
 * 时间基准只认 AudioContext.currentTime，不用 performance.now()——后者
 * 会与音频漂移，几分钟下来能差出小半秒。
 */

/** 该 stem 下有哪些视觉轨道。人声返回空数组——它驱动判定环，不占轨道。 */
export function lanesForStem(lanes, stem) {
  return lanes.filter((l) => l.stem === stem).map((l) => l.id);
}

/**
 * 静音状态。粒度是分轨——真歌四条，合成曲九条，由 timeline 顶层的
 * `stems` 字段声明，不再是写死的 4 个。
 */
export function createMuteState(stems) {
  const known = new Set(stems);
  const muted = new Set();
  return {
    muted,
    toggle(stem) {
      if (!known.has(stem)) throw new Error(`未知声部：${stem}`);
      if (muted.has(stem)) muted.delete(stem);
      else muted.add(stem);
    },
    isMuted(stem) {
      return muted.has(stem);
    },
    gainFor(stem) {
      return muted.has(stem) ? 0 : 1;
    },
  };
}

/** data URI → ArrayBuffer。不走网络层，因此 file:// 下也能用。 */
export function dataUriToArrayBuffer(uri) {
  const comma = uri.indexOf(",");
  if (!uri.startsWith("data:") || comma < 0) {
    throw new Error(`不是合法的 data: URI：${uri.slice(0, 40)}`);
  }
  const bin = atob(uri.slice(comma + 1));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

const MUTE_RAMP_S = 0.02;

/**
 * 按下播放键时该从哪一秒起播。
 *
 * **播完之后是从头，不是从结尾续播**——从结尾"续播"等于什么都不放，用户
 * 按了播放却听不到声音（上一棒坦白的四条之一）。抽成一个具名函数是为了
 * 能单测：它原本是 main.js 的 togglePlay 里的一个三元表达式，而 boot()
 * 里的闭包没有任何办法直接测。
 */
export function resumeFrom(player) {
  return player.ended ? 0 : player.currentTime();
}

/**
 * 分轨同步播放器。
 *
 * 各条 source 同时 start(0, seekT)，保证采样级同步。静音是把增益渐变到
 * 0 而不是 stop——stop 之后再起会失去同步。
 *
 * **三个状态要分清，不是一个：**
 *
 * - `running`：用户的播放/暂停意图。按了播放就是 true，按暂停才变 false。
 *   这一条就是本次改动之前的 `playing`，走带条的"松手要不要续播"看的是它。
 * - `ended`：已经走到曲末。
 * - `playing`：**此刻真的有声音**，即 `running && !ended`。走带条的播放键
 *   看的是它——改动之前键上看的是 running，于是曲子放完之后按键仍然显示
 *   ❚❚（"正在放"），而实际上一点声音都没有，界面在骗人。
 *
 * `duration` 缺省是 Infinity，也就是"永远不结束"，与改动之前逐字节同义。
 * 这样既有的两参数调用（audio.test.mjs 那几条）行为一个字都不变。
 *
 * **为什么用传进来的曲长，而不是 buffers 自己的 duration**：两者在真产物
 * 上是一回事——实测私仓 songs/01 的四条 m4a 都是 270.001995 秒，timeline
 * 的 meta.duration 是 270.0，差 2 毫秒。而 boot-harness.html 里的假 buffer
 * 是 12 秒、meta.duration 却写着 270，既有的 boot 测试会把假时钟推到 40 秒
 * ——按 buffer 时长判定会让那几条测试凭空变红。取显式传入的曲长两边都对。
 */
export function createPlayer(ctx, buffers, duration = Infinity) {
  // 总音量单独一个节点。不能拿各 stem 的静音增益兼作音量——两者一叠加，
  // 调过音量之后再取消静音就回不到原来的响度了。
  const master = ctx.createGain();
  master.connect(ctx.destination);

  // 增益节点按 buffers 实际有哪些 key 建——分轨数由 timeline 声明，不是
  // 写死的 4 个。九条分轨进来就建九个，否则后五条会静默没有增益节点，
  // applyMute 循环也就轮不到它们。
  const gains = {};
  for (const stem of Object.keys(buffers)) {
    const g = ctx.createGain();
    g.connect(master);
    gains[stem] = g;
  }

  let sources = [];
  let startedAt = 0;
  let offset = 0;
  let running = false;

  function stopSources() {
    for (const s of sources) {
      try {
        s.stop();
      } catch {
        /* 已停止 */
      }
    }
    sources = [];
  }

  /** 起播至今走了多久，**不钳**。越过曲长照涨，这是它的本分。 */
  function elapsed() {
    return running ? ctx.currentTime - startedAt + offset : offset;
  }

  return {
    /** 用户的播放/暂停意图。走带条"松手要不要续播"看这个，不看 playing。 */
    get running() {
      return running;
    },

    /** 已经走到曲末。缺省 duration 是 Infinity，那就永远是 false。 */
    get ended() {
      return elapsed() >= duration;
    },

    /** **此刻真的有声音。** 播放键看这个——曲子放完了就不该再显示"正在放"。 */
    get playing() {
      return running && !this.ended;
    },

    currentTime() {
      return Math.min(elapsed(), duration);
    },

    start(at = offset) {
      stopSources();
      offset = at;
      startedAt = ctx.currentTime;
      for (const stem of Object.keys(buffers)) {
        const buf = buffers[stem];
        if (!buf) continue;
        const src = ctx.createBufferSource();
        src.buffer = buf;
        src.connect(gains[stem]);
        src.start(0, at);
        sources.push(src);
      }
      running = true;
    },

    pause() {
      if (!running) return;
      offset = this.currentTime();
      stopSources();
      running = false;
    },

    seek(t) {
      const wasRunning = running;
      stopSources();
      offset = t;
      running = false;
      if (wasRunning) this.start(t);
    },

    setVolume(v) {
      master.gain.setTargetAtTime(
        Math.max(0, Math.min(1, v)),
        ctx.currentTime,
        MUTE_RAMP_S,
      );
    },

    applyMute(muteState) {
      // 只对真的建了增益节点的 stem 写增益——gains 的 key 集合就是
      // buffers 的 key 集合，与 muteState 认得的分轨列表理应一致。
      for (const stem of Object.keys(gains)) {
        gains[stem].gain.setTargetAtTime(
          muteState.gainFor(stem),
          ctx.currentTime,
          MUTE_RAMP_S,
        );
      }
    },
  };
}
