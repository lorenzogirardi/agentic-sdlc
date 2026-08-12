from flask import Flask, request, jsonify
import math

app = Flask(__name__)


def clamp(value, min_val, max_val):
    return max(min_val, min(max_val, value))


def compute_fractal(iterations, width, height, xmin, xmax, ymin, ymax, burning_ship=False):
    data = []
    for py in range(height):
        row = []
        y = ymin + (ymax - ymin) * py / (height - 1) if height > 1 else ymin
        for px in range(width):
            x = xmin + (xmax - xmin) * px / (width - 1) if width > 1 else xmin
            if burning_ship:
                zx = abs(x)
                zy = abs(y)
                c = complex(x, y)
            else:
                zx = 0.0
                zy = 0.0
                c = complex(x, y)
            n = 0
            while n < iterations:
                if burning_ship:
                    zx, zy = abs(zx) * abs(zx) - abs(zy) * abs(zy) + c.real, 2 * abs(zx) * abs(zy) + c.imag
                else:
                    zx, zy = zx * zx - zy * zy + c.real, 2 * zx * zy + c.imag
                if zx * zx + zy * zy > 4:
                    break
                n += 1
            row.append(n)
        data.append(row)
    return data


@app.route('/fractal', methods=['GET'])
def fractal():
    try:
        iterations = int(request.args.get('iterations', 100))
        width = int(request.args.get('width', 800))
        height = int(request.args.get('height', 600))
        xmin = float(request.args.get('xmin', -2.5))
        xmax = float(request.args.get('xmax', 1.5))
        ymin = float(request.args.get('ymin', -1.5))
        ymax = float(request.args.get('ymax', 1.5))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid query parameters'}), 400

    iterations = clamp(iterations, 1, 200)
    width = clamp(width, 100, 800)
    height = clamp(height, 75, 600)

    data = compute_fractal(iterations, width, height, xmin, xmax, ymin, ymax)
    return jsonify({'iterations': iterations, 'width': width, 'height': height, 'xmin': xmin, 'xmax': xmax, 'ymin': ymin, 'ymax': ymax, 'data': data})


@app.route('/burning-ship', methods=['GET'])
def burning_ship():
    try:
        iterations = int(request.args.get('iterations', 100))
        width = int(request.args.get('width', 800))
        height = int(request.args.get('height', 600))
        xmin = float(request.args.get('xmin', -2.5))
        xmax = float(request.args.get('xmax', 1.5))
        ymin = float(request.args.get('ymin', -1.5))
        ymax = float(request.args.get('ymax', 1.5))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid query parameters'}), 400

    iterations = clamp(iterations, 1, 200)
    width = clamp(width, 100, 800)
    height = clamp(height, 75, 600)

    data = compute_fractal(iterations, width, height, xmin, xmax, ymin, ymax, burning_ship=True)
    return jsonify({'iterations': iterations, 'width': width, 'height': height, 'xmin': xmin, 'xmax': xmax, 'ymin': ymin, 'ymax': ymax, 'data': data})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
