from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Sample Service")


@app.get("/")
async def root() -> HTMLResponse:
    return HTMLResponse(content=INDEX_HTML)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(content={"status": "ok"})


@app.get("/fractal")
async def fractal(
    iterations: int = 5,
    cx: float = -0.7,
    cy: float = 0.27015,
    width: int = 400,
    height: int = 300,
    zoom: float = 1.0,
) -> JSONResponse:
    max_iter = max(1, min(iterations, 20))
    w = max(100, min(width, 800))
    h = max(75, min(height, 600))

    points = _julia_set(w, h, cx, cy, zoom, max_iter)
    return JSONResponse(
        content={
            "type": "julia",
            "parameters": {"cx": cx, "cy": cy, "max_iterations": max_iter, "zoom": zoom},
            "width": w,
            "height": h,
            "points": points,
        }
    )


def _julia_set(w: int, h: int, cx: float, cy: float, zoom: float, max_iter: int) -> list[list[int]]:
    aspect = w / h
    scale_x = 3.0 / zoom
    scale_y = 3.0 / zoom / aspect

    result: list[list[int]] = []
    for py in range(h):
        row: list[int] = []
        for px in range(w):
            zx = (px / w - 0.5) * scale_x
            zy = (py / h - 0.5) * scale_y
            iteration = 0
            while zx * zx + zy * zy < 4.0 and iteration < max_iter:
                xtemp = zx * zx - zy * zy + cx
                zy = 2.0 * zx * zy + cy
                zx = xtemp
                iteration += 1
            row.append(iteration)
        result.append(row)
    return result


INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Julia Set Explorer</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0d1117; color: #c9d1d9; display: flex; flex-direction: column; align-items: center; min-height: 100vh; padding: 2rem; }
        h1 { font-size: 1.5rem; margin-bottom: 1rem; color: #58a6ff; }
        canvas { border: 1px solid #30363d; border-radius: 8px; cursor: pointer; }
        .controls { display: flex; gap: 0.5rem; margin: 1rem 0; flex-wrap: wrap; justify-content: center; align-items: center; }
        button, input { padding: 0.4rem 0.8rem; border: 1px solid #30363d; border-radius: 6px; background: #21262d; color: #c9d1d9; font-size: 0.85rem; }
        button:hover { background: #30363d; cursor: pointer; }
        label { font-size: 0.85rem; }
        #info { font-size: 0.8rem; color: #8b949e; margin-top: 0.5rem; }
        .status { font-size: 0.8rem; color: #3fb950; }
    </style>
</head>
<body>
    <h1>Julia Set Explorer</h1>
    <canvas id="canvas" width="400" height="300"></canvas>
    <div class="controls">
        <button onclick="resetView()">Reset</button>
        <button onclick="zoomIn()">Zoom In</button>
        <button onclick="zoomOut()">Zoom Out</button>
        <label>Iterations: <input type="range" id="iterSlider" min="1" max="20" value="5" oninput="updateFractal()"></label>
        <label>Zoom: <input type="range" id="zoomSlider" min="1" max="100" value="10" oninput="updateFractal()"></label>
    </div>
    <div class="status" id="status">✔ Health: ok</div>
    <div id="info">Click anywhere on the canvas to center the view</div>
    <script>
        let cx = -0.7, cy = 0.27015, width = 400, height = 300;
        const canvas = document.getElementById('canvas');
        const ctx = canvas.getContext('2d');

        function palette(iter, max) {
            if (iter >= max) return [0, 0, 0];
            const t = iter / max;
            const r = Math.floor(9 * (1 - t) * t * t * t * 255);
            const g = Math.floor(15 * (1 - t) * (1 - t) * t * t * 255);
            const b = Math.floor(8.5 * (1 - t) * (1 - t) * (1 - t) * t * 255);
            return [r, g, b];
        }

        async function updateFractal() {
            const iterations = parseInt(document.getElementById('iterSlider').value);
            const zoom = parseInt(document.getElementById('zoomSlider').value);
            const resp = await fetch(`/fractal?iterations=${iterations}&cx=${cx}&cy=${cy}&width=${width}&height=${height}&zoom=${zoom}`);
            const data = await resp.json();
            const imgData = ctx.createImageData(data.width, data.height);
            for (let y = 0; y < data.height; y++) {
                for (let x = 0; x < data.width; x++) {
                    const [r, g, b] = palette(data.points[y][x], iterations);
                    const idx = (y * data.width + x) * 4;
                    imgData.data[idx] = r;
                    imgData.data[idx + 1] = g;
                    imgData.data[idx + 2] = b;
                    imgData.data[idx + 3] = 255;
                }
            }
            ctx.putImageData(imgData, 0, 0);
        }

        canvas.addEventListener('click', async (e) => {
            const rect = canvas.getBoundingClientRect();
            const zoom = parseInt(document.getElementById('zoomSlider').value) / 10;
            const scaleX = 3.0 / zoom;
            const scaleY = 3.0 / zoom / (width / height);
            cx += (e.clientX - rect.left) / width * scaleX - scaleX / 2;
            cy += (e.clientY - rect.top) / height * scaleY - scaleY / 2;
            updateFractal();
        });

        function zoomIn() { document.getElementById('zoomSlider').value = Math.min(100, parseInt(document.getElementById('zoomSlider').value) + 10); updateFractal(); }
        function zoomOut() { document.getElementById('zoomSlider').value = Math.max(1, parseInt(document.getElementById('zoomSlider').value) - 10); updateFractal(); }
        function resetView() { cx = -0.7; cy = 0.27015; document.getElementById('zoomSlider').value = 10; document.getElementById('iterSlider').value = 5; updateFractal(); }

        fetch('/health').then(r => r.json()).then(d => { document.getElementById('status').textContent = `✔ Health: ${d.status}`; }).catch(() => { document.getElementById('status').textContent = '✘ Health: unreachable'; });
        updateFractal();
    </script>
</body>
</html>"""
