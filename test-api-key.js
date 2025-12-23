const axios = require('axios');

async function testApiKey() {
    const apiKey = 't65TZi90SPqdOlvJ56NwOJryloouyfzB0';

    console.log('Testing ConvertAPI key:', apiKey);
    console.log('Key length:', apiKey.length);

    try {
        // Test with a simple API call to get user info
        const response = await axios.get('https://v2.convertapi.com/user', {
            headers: {
                'Authorization': `Bearer ${apiKey}`
            }
        });

        console.log('✓ API Key is VALID');
        console.log('User info:', response.data);
    } catch (error) {
        if (error.response) {
            console.log('✗ API Key is INVALID or EXPIRED');
            console.log('Status:', error.response.status);
            console.log('Error:', error.response.data);

            if (error.response.status === 401) {
                console.log('\n⚠ The API key is not authorized. Please:');
                console.log('1. Go to https://www.convertapi.com/');
                console.log('2. Sign up for a FREE account (or log in)');
                console.log('3. Go to your dashboard and copy your API Secret');
                console.log('4. Replace the value in .env.local with the new secret');
            }
        } else {
            console.log('Network error:', error.message);
        }
    }
}

testApiKey();
