export function createVoiceAudio(url, { AudioClass = globalThis.Audio, maxPlaybackMs = 30000 } = {}) {
  const audio = new AudioClass(url);
  audio.preload = 'auto';
  let cancel;
  return {
    play() {
      return new Promise((resolve, reject) => {
        let finished = false, timeout;
        const finish = error => {
          if (finished) return;
          finished = true; cancel = null; clearTimeout(timeout);
          audio.removeEventListener('ended', ended); audio.removeEventListener('error', failed);
          error ? reject(error) : resolve();
        };
        const ended = () => finish();
        const failed = () => finish(Object.assign(new Error('录音播放异常，请检查声音设置后重试'), { code: 'notification_audio' }));
        cancel = () => { audio.pause(); finish(new DOMException('播报已停止', 'AbortError')); };
        audio.addEventListener('ended', ended); audio.addEventListener('error', failed);
        timeout = setTimeout(() => {
          audio.pause();
          finish(Object.assign(new Error('录音播放超时，请点击恢复监听'), { code: 'notification_audio' }));
        }, maxPlaybackMs);
        // Called directly by the button gesture, before any await/network/IDB work.
        try { audio.currentTime = 0; audio.play().catch(error => finish(error)); } catch (error) { finish(error); }
      });
    },
    stop() { cancel?.(); audio.pause(); },
  };
}
