import sharp from 'sharp';
import { createCanvas, loadImage } from 'canvas';

export interface BoundingBox {
    x: number;
    y: number;
    width: number;
    height: number;
}

export interface TextBlock {
    text: string;
    boundingBox: BoundingBox;
    confidence: number;
}

export interface TextBlockWithTranslation extends TextBlock {
    translatedText: string;
}

export async function removeTextWithFill(imagePath: string, boundingBoxes: BoundingBox[]): Promise<Buffer> {
    const image = sharp(imagePath);
    const metadata = await image.metadata();

    if (!metadata.width || !metadata.height) {
        throw new Error('Could not get image metadata');
    }

    const imageBuffer = await image.toBuffer();
    const { data, info } = await sharp(imageBuffer).raw().toBuffer({ resolveWithObject: true });

    for (const box of boundingBoxes) {
        const padding = 10;
        const startX = Math.max(0, box.x - padding);
        const startY = Math.max(0, box.y - padding);
        const endX = Math.min(info.width, box.x + box.width + padding);
        const endY = Math.min(info.height, box.y + box.height + padding);
        const regionWidth = endX - startX;
        const regionHeight = endY - startY;

        if (regionWidth <= 0 || regionHeight <= 0) continue;

        const r: number[] = [];
        const g: number[] = [];
        const b: number[] = [];

        for (let y = startY; y < endY; y++) {
            for (let x = startX; x < endX; x++) {
                const i = (y * info.width + x) * 3;
                r.push(data[i]);
                g.push(data[i + 1]);
                b.push(data[i + 2]);
            }
        }

        const avgR = Math.round(r.reduce((a, b) => a + b, 0) / r.length);
        const avgG = Math.round(g.reduce((a, b) => a + b, 0) / g.length);
        const avgB = Math.round(b.reduce((a, b) => a + b, 0) / b.length);

        for (let y = box.y; y < box.y + box.height; y++) {
            for (let x = box.x; x < box.x + box.width; x++) {
                const i = (y * info.width + x) * 3;
                data[i] = avgR;
                data[i + 1] = avgG;
                data[i + 2] = avgB;
            }
        }
    }

    return await sharp(data, { raw: { width: info.width, height: info.height, channels: 3 } }).toBuffer();
}

export async function overlayText(
    imageBuffer: Buffer,
    textBlocks: TextBlockWithTranslation[],
    targetLanguage: string
): Promise<Buffer> {
    const image = await loadImage(imageBuffer);
    const canvas = createCanvas(image.width, image.height);
    const ctx = canvas.getContext('2d');

    ctx.drawImage(image, 0, 0);

    const isJapanese = targetLanguage === 'ja';

    for (const block of textBlocks) {
        const { text, boundingBox } = block;
        const displayText = block.translatedText || text;

        const fontSize = Math.floor(Math.min(boundingBox.height, 72));
        const fontFamily = isJapanese
            ? '"MS Gothic", "Hiragino Kaku Gothic Pro", "Noto Sans JP", sans-serif'
            : '"Arial", "Noto Sans", sans-serif';

        ctx.font = `${fontSize}px ${fontFamily}`;
        ctx.fillStyle = '#000000';
        ctx.textBaseline = 'top';

        const words = displayText.split(' ');
        let line = '';
        let y = boundingBox.y;
        const lineHeight = fontSize * 1.2;

        if (isJapanese) {
            ctx.fillText(displayText, boundingBox.x, y);
        } else {
            for (const word of words) {
                const testLine = line + word + ' ';
                const metrics = ctx.measureText(testLine);

                if (metrics.width > boundingBox.width && line !== '') {
                    ctx.fillText(line, boundingBox.x, y);
                    line = word + ' ';
                    y += lineHeight;
                } else {
                    line = testLine;
                }
            }
            ctx.fillText(line, boundingBox.x, y);
        }
    }

    return canvas.toBuffer('image/jpeg');
}

export function getLanguage(text: string): string {
    if (/[\u3040-\u309F\u30A0-\u30FF]/.test(text)) {
        return 'ja';
    }
    return 'en';
}

export function detectTargetLanguage(detectedLanguage: string): string {
    if (detectedLanguage === 'ja') {
        return 'en';
    } else if (detectedLanguage === 'en') {
        return 'ja';
    }
    return 'en';
}
