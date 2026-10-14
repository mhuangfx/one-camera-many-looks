#!/usr/bin/env python3
"""Local route: render one look from the blocking video on your own GPU with ComfyUI.

Two stages, both sent to a running ComfyUI server through its HTTP API:
  1. First frame: Qwen Image Edit turns frame 0 of the blocking into the look (layout kept).
  2. Video: Wan 2.2 Fun Control animates that frame. The control signal is the depth of every
     blocking frame, so the camera path, framing, and timing come from the blocking.

Usage:
  python3 comfyui/run_look.py --blocking media/blocking.mp4 --look looks/look1_luxury/prompt.txt \
      --out out/look1_local [--server 127.0.0.1:8188] [--frames 121 --fps 12] [--seed 7]

Needs ComfyUI with ComfyUI-WanVideoWrapper, ComfyUI-KJNodes, ComfyUI-VideoHelperSuite, and
comfyui-nikosis-preprocessors, and the models listed in comfyui/README.md. Stdlib only, plus ffmpeg.
The two workflows are also saved as API-format JSON next to the output, so they can be opened in
ComfyUI.
"""
import argparse, json, os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request, uuid

# Models (file names as ComfyUI lists them)
QWEN_EDIT = "qwen_image_edit_2509_fp8_e4m3fn.safetensors"
QWEN_LORA = "Qwen-Image-Edit-2509-Lightning-8steps-V1.0-bf16.safetensors"
QWEN_CLIP = "qwen_2.5_vl_7b_fp8_scaled.safetensors"
QWEN_VAE = "qwen_image_vae.safetensors"
FUN_HIGH = "Fun/Wan2_2-Fun-Control-A14B-HIGH_fp8_e4m3fn_scaled_KJ_fixed.safetensors"
FUN_LOW = "Fun/Wan2_2-Fun-Control-A14B-LOW_fp8_e4m3fn_scaled_KJ_fixed.safetensors"
WAN_VAE = "wanvideo/Wan2_1_VAE_bf16.safetensors"
WAN_TEXT = "umt5_xxl_fp16.safetensors"
WAN_LORA = "WanVideo/Lightx2v/lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank32_bf16.safetensors"
DEPTH = "depth_anything_v2_vitl_fp16.safetensors"

NEG = ("flat colors, simple shapes, untextured blocks, toy, low detail, blurry, text, logo, watermark, "
       "cut, scene change, distorted car, extra wheels")


def look_text(path):
    """The [Look] section of a look prompt (camera lines are not needed: depth carries the camera)."""
    t = open(path).read()
    m = re.search(r"\[Look\]\s*(.+?)(?:\n<|\Z)", t, re.S)
    return (m.group(1) if m else t).strip()


# ---------- ComfyUI HTTP helpers ----------
def api(server, path, data=None, ctype="application/json"):
    req = urllib.request.Request(f"http://{server}{path}", data=data,
                                 headers={"Content-Type": ctype} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"ComfyUI {path}: HTTP {e.code}: {e.read().decode(errors='replace')[:1500]}")


def upload(server, path):
    boundary = uuid.uuid4().hex
    name = os.path.basename(path)
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + open(path, "rb").read() + \
           f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n".encode()
    return json.loads(api(server, "/upload/image", body, f"multipart/form-data; boundary={boundary}"))["name"]


def run(server, workflow, label):
    pid = json.loads(api(server, "/prompt", json.dumps({"prompt": workflow}).encode()))["prompt_id"]
    t0 = time.time()
    while True:
        h = json.loads(api(server, f"/history/{pid}"))
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error":
                sys.exit(f"{label} failed: {json.dumps(st.get('messages', []))[:800]}")
            if st.get("completed"):
                print(f"{label}: done in {time.time() - t0:.0f} s", flush=True)
                return h[pid]["outputs"]
        time.sleep(5)


def fetch(server, item, out_path):
    q = urllib.parse.urlencode({"filename": item["filename"], "subfolder": item.get("subfolder", ""),
                                "type": item.get("type", "output")})
    open(out_path, "wb").write(api(server, f"/view?{q}"))
    return out_path


# ---------- workflows (API format) ----------
def first_frame_workflow(image, look, seed):
    edit = ("Re-render this simple 3D blocking frame as a finished film frame. Keep the composition "
            "exactly: the same camera angle, horizon, and street, and the car at the same position and the "
            "same size in the frame as the red box car, seen from the same side. Replace each colored block "
            "with the building or object it stands for. The car is an unbadged design with a plain, "
            "unbranded grille and no hood ornament. " + look)
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": QWEN_EDIT, "weight_dtype": "default"}},
        "2": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": QWEN_LORA, "strength_model": 1.0}},
        "3": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["2", 0], "shift": 3.0}},
        "4": {"class_type": "CLIPLoader", "inputs": {"clip_name": QWEN_CLIP, "type": "qwen_image", "device": "default"}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": QWEN_VAE}},
        "6": {"class_type": "LoadImage", "inputs": {"image": image}},
        "7": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["6", 0], "upscale_method": "lanczos", "megapixels": 1.0, "resolution_steps": 16}},
        "8": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["4", 0], "prompt": edit, "vae": ["5", 0], "image1": ["7", 0]}},
        "9": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["4", 0], "prompt": "", "vae": ["5", 0], "image1": ["7", 0]}},
        "10": {"class_type": "VAEEncode", "inputs": {"pixels": ["7", 0], "vae": ["5", 0]}},
        "11": {"class_type": "KSampler", "inputs": {"model": ["3", 0], "positive": ["8", 0], "negative": ["9", 0],
               "latent_image": ["10", 0], "seed": seed, "steps": 8, "cfg": 1.0, "sampler_name": "euler",
               "scheduler": "simple", "denoise": 1.0}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["5", 0]}},
        "13": {"class_type": "SaveImage", "inputs": {"images": ["12", 0], "filename_prefix": "look_first_frame"}},
    }


def video_workflow(video, first, look, w, h, frames, fps, seed, steps=6, switch=3, control=1.0, control_end=1.0):
    def resize(src):
        return {"image": src, "width": w, "height": h, "upscale_method": "lanczos", "keep_proportion": "crop",
                "pad_color": "0, 0, 0", "crop_position": "center", "divisible_by": 16, "device": "cpu"}
    swap = {"blocks_to_swap": 25, "offload_img_emb": False, "offload_txt_emb": False, "use_non_blocking": True,
            "vace_blocks_to_swap": 0, "prefetch_blocks": 0, "block_swap_debug": False}
    lora = {"lora": WAN_LORA, "strength": 1.5, "low_mem_load": False, "merge_loras": True}
    loader = lambda m, l: {"model": m, "base_precision": "fp16_fast", "quantization": "fp8_e4m3fn_scaled",
                           "load_device": "offload_device", "attention_mode": "sageattn",
                           "lora": [l, 0], "block_swap_args": ["5", 0]}
    sampler = lambda model, samples, start, end: {
        "model": [model, 0], "image_embeds": ["13", 0], "text_embeds": ["14", 0], "steps": steps, "cfg": 1.0,
        "shift": 5.0, "seed": seed, "force_offload": True, "scheduler": "dpm++_sde", "riflex_freq_index": 0,
        "start_step": start, "end_step": end, **({"samples": [samples, 0]} if samples else {})}
    wf = {
        "5": {"class_type": "WanVideoBlockSwap", "inputs": swap},
        "40": {"class_type": "WanVideoLoraSelect", "inputs": lora},
        "41": {"class_type": "WanVideoLoraSelect", "inputs": lora},
        "1": {"class_type": "WanVideoModelLoader", "inputs": loader(FUN_HIGH, "40")},
        "18": {"class_type": "WanVideoModelLoader", "inputs": loader(FUN_LOW, "41")},
        "2": {"class_type": "WanVideoVAELoader", "inputs": {"model_name": WAN_VAE, "precision": "bf16"}},
        # blocking video -> depth for every frame (the camera)
        "6": {"class_type": "VHS_LoadVideo", "inputs": {"video": video, "force_rate": fps, "custom_width": 0,
              "custom_height": 0, "frame_load_cap": frames, "skip_first_frames": 0, "select_every_nth": 1}},
        "7": {"class_type": "ImageResizeKJv2", "inputs": resize(["6", 0])},
        "8": {"class_type": "DepthAnythingV2Nikosis", "inputs": {"images": ["7", 0], "model": DEPTH,
              "manual_resolution": False, "resolution": 1024}},
        "11": {"class_type": "WanVideoImageToVideoEncode", "inputs": {"width": w, "height": h, "num_frames": frames,
               "noise_aug_strength": 0.0, "start_latent_strength": 1.0, "end_latent_strength": 1.0,
               "force_offload": True, "fun_or_fl2v_model": True, "vae": ["2", 0]}},
        "12": {"class_type": "WanVideoEncode", "inputs": {"vae": ["2", 0], "image": ["8", 0], "enable_vae_tiling": False,
               "tile_x": 272, "tile_y": 272, "tile_stride_x": 144, "tile_stride_y": 128,
               "noise_aug_strength": 0.0, "latent_strength": control}},
        "13": {"class_type": "WanVideoAddControlEmbeds", "inputs": {"embeds": ["11", 0], "start_percent": 0.0,
               "end_percent": control_end, "latents": ["12", 0]}},
        "14": {"class_type": "WanVideoTextEncodeCached", "inputs": {"model_name": WAN_TEXT, "precision": "bf16",
               "positive_prompt": look, "negative_prompt": NEG, "quantization": "fp8_e4m3fn",
               "use_disk_cache": True, "device": "gpu"}},
        # Wan 2.2 two experts: HIGH lays out motion, LOW refines detail
        "15": {"class_type": "WanVideoSampler", "inputs": sampler("1", None, 0, switch)},
        "19": {"class_type": "WanVideoSampler", "inputs": sampler("18", "15", switch, -1)},
        "16": {"class_type": "WanVideoDecode", "inputs": {"vae": ["2", 0], "samples": ["19", 0], "enable_vae_tiling": False,
               "tile_x": 272, "tile_y": 272, "tile_stride_x": 144, "tile_stride_y": 128}},
        "17": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["16", 0], "frame_rate": fps, "loop_count": 0,
               "filename_prefix": "look_local", "format": "video/h264-mp4", "pingpong": False, "save_output": True}},
    }
    if first:  # styled first frame anchors the look
        wf["9"] = {"class_type": "LoadImage", "inputs": {"image": first}}
        wf["10"] = {"class_type": "ImageResizeKJv2", "inputs": resize(["9", 0])}
        wf["11"]["inputs"]["start_image"] = ["10", 0]
    return wf


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--blocking", required=True)
    ap.add_argument("--look", required=True, help="a looks/*/prompt.txt file")
    ap.add_argument("--out", required=True)
    ap.add_argument("--server", default="127.0.0.1:8188")
    ap.add_argument("--width", type=int, default=832)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--frames", type=int, default=117, help="4n+1; 117 at 12 fps covers 9.75 s of the blocking")
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--first-frame-only", action="store_true", help="stop after stage 1 (to pick a seed)")
    ap.add_argument("--first-frame", help="skip stage 1 and use this image as the first frame")
    ap.add_argument("--steps", type=int, default=8, help="total steps; the HIGH expert takes the first half")
    ap.add_argument("--control", type=float, default=0.5, help="depth strength: higher = closer to the blocking shapes")
    ap.add_argument("--control-end", type=float, default=0.4, help="stop depth control after this share of the steps")
    ap.add_argument("--text-only", action="store_true", help="skip stage 1; the look comes from the text alone")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    look = look_text(a.look)

    frame0 = os.path.join(a.out, "blocking_f0.png")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", a.blocking, "-frames:v", "1", frame0], check=True)
    img = upload(a.server, frame0)
    vid = upload(a.server, a.blocking)

    if a.text_only:
        first = None
    elif a.first_frame:
        first = a.first_frame
    else:
        wf1 = first_frame_workflow(img, look, a.seed)
        json.dump(wf1, open(os.path.join(a.out, "workflow_first_frame.json"), "w"), indent=1)
        out1 = run(a.server, wf1, "first frame")
        first = fetch(a.server, out1["13"]["images"][0], os.path.join(a.out, f"first_frame_s{a.seed}.png"))
        if a.first_frame_only:
            return print(first)

    wf2 = video_workflow(vid, upload(a.server, first) if first else None, look, a.width, a.height, a.frames, a.fps, a.seed,
                         steps=a.steps, switch=a.steps // 2,
                         control=a.control, control_end=a.control_end)
    json.dump(wf2, open(os.path.join(a.out, "workflow_video.json"), "w"), indent=1)
    out2 = run(a.server, wf2, "video")
    item = out2["17"]["gifs"][0]
    print(fetch(a.server, item, os.path.join(a.out, "look.mp4")))


if __name__ == "__main__":
    main()
