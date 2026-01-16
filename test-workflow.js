const axios = require('axios');
const fs = require('fs');

async function testFullWorkflow() {
    const pptxPath = "C:\\Users\\Ammar.Zolkipli\\OneDrive - globallogic.com\\Documents\\Accelerating the 'AI-Native' Transformation.pptx";
    const port = process.argv[2] || 3016;
    
    console.log('1. Testing upload API...');
    console.log('   (Using LibreOffice for local PPTX → JPG conversion)\n');
    
    try {
        const uploadForm = new FormData();
        const fileBuffer = fs.readFileSync(pptxPath);
        const blob = new Blob([fileBuffer]);
        uploadForm.append('file', blob, 'test.pptx');
        
        const uploadResponse = await axios.post(`http://localhost:${port}/api/upload`, uploadForm, {
            headers: { 'Content-Type': 'multipart/form-data' }
        });
        
        console.log(`✓ Upload successful!`);
        console.log(`  Generated ${uploadResponse.data.images.length} slide(s)\n`);
        
        // Test translation on first slide
        console.log('2. Testing translation API...');
        console.log('   (Using OCR.space for text extraction, LibreTranslate for translation)\n');
        
        const firstImage = uploadResponse.data.images[0];
        const base64Data = firstImage.url.split(',')[1];
        
        console.log(`   Image data length: ${base64Data.length} characters`);
        console.log(`   First 50 chars: ${base64Data.substring(0, 50)}...\n`);
        
        const translateResponse = await axios.post(`http://localhost:${port}/api/translate`, {
            imageData: base64Data
        });
        
        console.log('✓ Translation successful!');
        console.log('\n📄 Original Text (first 200 chars):');
        console.log('   ' + (translateResponse.data.originalText?.substring(0, 200) || '(empty)'));
        console.log('\n🌍 Translated Text (first 200 chars):');
        console.log('   ' + (translateResponse.data.translatedText?.substring(0, 200) || '(empty)'));
        console.log('\n📊 Detection: ' + translateResponse.data.detectedLanguage + ' → ' + translateResponse.data.targetLanguage);
        console.log('🖼️  Processed image generated: ' + (translateResponse.data.imageUrl ? 'Yes' : 'No'));
        
        console.log('\n========================================');
        console.log('✅ Full workflow test PASSED!');
        console.log('========================================');
        
    } catch (error) {
        console.error('\n❌ Error:', error.response?.data || error.message);
        if (error.response?.data?.suggestion) {
            console.log('\n💡 ' + error.response.data.suggestion);
        }
    }
}

testFullWorkflow();
