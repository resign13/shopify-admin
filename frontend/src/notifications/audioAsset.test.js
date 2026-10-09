import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';

const recording=readFileSync(new URL('../assets/new-order-zh-CN.wav',import.meta.url));
const metadata=JSON.parse(readFileSync(new URL('../assets/new-order-zh-CN.json',import.meta.url),'utf8'));
const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
const chunk=name=>{
  for(let offset=12;offset+8<=recording.length;) {
    const length=recording.readUInt32LE(offset+4);
    if(recording.toString('ascii',offset,offset+4)===name) return recording.subarray(offset+8,offset+8+length);
    offset+=8+length+(length%2);
  }
  throw new Error(`Missing WAV ${name} chunk`);
};

test('deployed fixed recording uses the requested trade-department phrase and voice',()=>{
  assert.equal(metadata.phraseText,'您有新的外贸部订单，请注意查收。');
  assert.equal(metadata.voice,'Microsoft Huihui Desktop');assert.equal(metadata.repeatCount,2);
  assert.equal(recording.toString('ascii',0,4),'RIFF');assert.equal(recording.toString('ascii',8,12),'WAVE');
  assert.equal(digest(recording),metadata.wavSha256);
  const format=chunk('fmt ');
  assert.equal(format.readUInt16LE(0),1);assert.equal(format.readUInt16LE(2),metadata.channels);
  assert.equal(format.readUInt32LE(4),metadata.sampleRate);assert.equal(format.readUInt16LE(14),metadata.sampleWidth*8);
});

test('every complete audio clip contains exactly two identical phrases separated by 500ms silence',()=>{
  const data=chunk('data'),frameBytes=metadata.channels*metadata.sampleWidth;
  const phraseBytes=metadata.phraseFrameCount*frameBytes,pauseBytes=metadata.pauseFrameCount*frameBytes;
  assert.equal(metadata.pauseMs,500);assert.equal(metadata.pauseFrameCount,Math.round(metadata.sampleRate*0.5));
  assert.equal(data.length,phraseBytes*2+pauseBytes);
  assert.equal(digest(data.subarray(0,phraseBytes)),metadata.phrasePcmSha256);
  assert.ok(data.subarray(phraseBytes,phraseBytes+pauseBytes).every(byte=>byte===0));
  assert.ok(data.subarray(0,phraseBytes).equals(data.subarray(phraseBytes+pauseBytes)));
  assert.ok(data.subarray(0,phraseBytes).some(byte=>byte!==0));
});
