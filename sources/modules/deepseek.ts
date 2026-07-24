import axios from "axios";
import { keys } from "../keys";

const headers = {
    'Authorization': `Bearer ${keys.deepseek}`,
    'Content-Type': 'application/json'
};

export async function deepseekRequest(systemPrompt: string, userPrompt: string) {
    try {
        console.info("调用 DeepSeek API...");
        const response = await axios.post("https://api.deepseek.com/v1/chat/completions", {
            model: "deepseek-chat",
            messages: [
                { role: "system", content: systemPrompt },
                { role: "user", content: userPrompt },
            ],
            temperature: 0.7,
            max_tokens: 1024,
        }, { headers });
        return response.data.choices[0].message.content;
    } catch (error) {
        console.error("Error in deepseekRequest:", error);
        return null;
    }
}
