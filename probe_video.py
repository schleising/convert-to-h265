#!/usr/bin/env python3
import json
import os
import subprocess
import sys

def get_base_metrics(file_path):
    """
    Extracts core container attributes to determine file height and accurate middle duration.
    """
    cmd = [
        'ffprobe', '-v', 'error',
        '-i', file_path,
        '-select_streams', 'v:0',
        '-show_entries', 'stream=height,duration',
        '-of', 'json'
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        if not data.get('streams'):
            return None
        
        stream = data['streams'][0]
        height = int(stream.get('height', 0))
        duration = float(stream.get('duration', 0))
        
        if duration <= 0:
            duration = 600.0
            
        return {"height": height, "duration": duration}
    except Exception:
        return None

def analyze_packet_complexity(file_path, midpoint_seek):
    """
    Queries raw packet allocation data directly from the container layout.
    Bypasses MKV frame-seeking errors entirely.
    """
    # Using -read_intervals ensures ffprobe seeks accurately within the file
    seek_str = f"{int(midpoint_seek)}%+{int(midpoint_seek + 5)}"
    
    cmd = [
        'ffprobe', '-v', 'error',
        '-read_intervals', seek_str,
        '-i', file_path,
        '-select_streams', 'v:0',
        '-show_packets',
        '-show_entries', 'packet=flags,size',
        '-of', 'json'
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        packets = data.get('packets', [])
        
        if not packets:
            return None
            
        # Keyframes are flagged with a 'K' in packet metadata (e.g., 'K__')
        i_sizes = [int(p['size']) for p in packets if 'flags' in p and 'K' in p['flags'] and 'size' in p]
        pb_sizes = [int(p['size']) for p in packets if 'flags' in p and 'K' not in p['flags'] and 'size' in p]
        
        # Fallback group logic if the stream container doesn't explicitly pass keyframe flags
        if not i_sizes:
            # Assume largest 5% of packets are keyframes as a logical safety net
            packets_sorted = sorted([int(p['size']) for p in packets if 'size' in p])
            split_idx = int(len(packets_sorted) * 0.95)
            pb_sizes = packets_sorted[:split_idx]
            i_sizes = packets_sorted[split_idx:]

        avg_i = sum(i_sizes) / len(i_sizes) if i_sizes else 0
        avg_pb = sum(pb_sizes) / len(pb_sizes) if pb_sizes else 0
        grain_ratio = avg_i / avg_pb if avg_pb > 0 else 0
        
        return {
            "total_packets_sampled": len(packets),
            "avg_i_frame_bytes": avg_i,
            "avg_pb_frame_bytes": avg_pb,
            "grain_ratio": grain_ratio
        }
    except Exception as e:
        print(f"[-] Packet analyzer encountered an issue: {e}", file=sys.stderr)
        return None

def make_routing_decision(height, grain_ratio):
    """
    Applies the rule matrix logic based on technical boundaries.
    """
    if 0.1 < grain_ratio < 2.2:
        return {
            "encoder": "libx265 (CPU)",
            "reason": "Heavy visual noise/grain ratio detected. Hardware encoders will struggle or bloat.",
            "recommended_flags": "-c:v libx265 -crf 23 -preset medium"
        }
    
    if height <= 720:
        return {
            "encoder": "hevc_videotoolbox (M2 Hardware)",
            "reason": "Clean 720p (or lower) video. Stepping quality down to force it beneath the hardware bitrate floor.",
            "recommended_flags": "-c:v hevc_videotoolbox -q:v 41 -g 240 -keyint_min 240 -realtime 0"
        }
        
    return {
        "encoder": "hevc_videotoolbox (M2 Hardware)",
        "reason": "Clean 1080p+ video source. Optimal fit for M2 Silicon acceleration.",
        "recommended_flags": "-c:v hevc_videotoolbox -q:v 50 -g 240 -keyint_min 240 -realtime 0"
    }

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 probe_video.py <path_to_video_file>")
        sys.exit(1)
        
    target_file = sys.argv[1]
    if not os.path.exists(target_file):
        print(f"[-] Error: File not found at '{target_file}'")
        sys.exit(1)
        
    print(f"[+] Probing target file structural properties: {os.path.basename(target_file)}")
    
    # Step 1: Structural Scan
    base = get_base_metrics(target_file)
    if not base:
        print("[-] Error: Failed to retrieve video parameters from stream.")
        sys.exit(1)
        
    # Step 2: Packet Data Scan
    midpoint = base["duration"] / 2
    analysis = analyze_packet_complexity(target_file, midpoint)
    
    if not analysis:
        print("[-] Error: Could not isolate or evaluate internal video framework chunks.")
        sys.exit(1)
        
    # Step 3: Run Engine Decision Logic
    decision = make_routing_decision(base["height"], analysis["grain_ratio"])
    
    # Format and Output report data
    print("\n" + "="*50)
    print("           VIDEO AUTOMATION PROFILE REPORT       ")
    print("="*50)
    print(f" File Profiled:       {os.path.basename(target_file)}")
    print(f" Target Resolution:   {base['height']}p")
    print(f" Total Probe Sample:  {analysis['total_packets_sampled']} container packets analyzed")
    print(f" Avg Keyframe (I):    {analysis['avg_i_frame_bytes']:.0f} bytes")
    print(f" Avg Delta (P/B):     {analysis['avg_pb_frame_bytes']:.0f} bytes")
    print(f" Calculated Ratio:    {analysis['grain_ratio']:.2f}")
    print("-"*50)
    print(f" AUTOMATED ACTION:    Route to -> {decision['encoder']}")
    print(f" Rationale:           {decision['reason']}")
    print("-"*50)
    print(" Suggested Command Implementation:")
    print(f" ffmpeg -i \"{os.path.basename(target_file)}\" {decision['recommended_flags']} -c:a copy -c:s copy -map 0 output.mkv")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()