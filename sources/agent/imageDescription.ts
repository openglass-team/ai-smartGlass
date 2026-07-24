import { KnownModel, ollamaInference } from "../modules/ollama";
import { groqRequest } from "../modules/groq-llama3";
import { gptRequest } from "../modules/openai";
import { deepseekRequest } from "../modules/deepseek";


export async function imageDescription(src: Uint8Array, model: KnownModel = 'moondream:1.8b-v2-fp16'): Promise<string> {
    return ollamaInference({
        model: model,
        messages: [{
            role: 'system',
            content: 'You are a very advanced model and your task is to describe the image as precisely as possible. Transcribe any text you see.'
        }, {
            role: 'user',
            content: 'Describe the scene',
            images: [src],
        }]
    });
}

export async function llamaFind(question: string, images: string): Promise<string> {
    return groqRequest(
             `
                You are a smart AI that need to read through description of a images and answer user's questions.

                This are the provided images:
                ${images}

                DO NOT mention the images, scenes or descriptions in your answer, just answer the question.
                DO NOT try to generalize or provide possible scenarios.
                ONLY use the information in the description of the images to answer the question.
                BE concise and specific.
            `
        ,
            question
    );
}

export async function deepseekFind(question: string, images: string): Promise<string> {
    return deepseekRequest(
             `
                你是一个智能 AI，需要根据图片的文字描述来回答用户的问题。

                以下是提供的图片描述：
                ${images}

                不要提及图片、场景或描述本身，只回答问题。
                不要臆测或提供假设性场景。
                只使用图片描述中的信息来回答问题。
                保持简洁和具体。用中文回答。
            `
        ,
            question
    );
}

export async function openAIFind(question: string, images: string): Promise<string> {
    return gptRequest(
             `
                You are a smart AI that need to read through description of a images and answer user's questions.

                This are the provided images:
                ${images}

                DO NOT mention the images, scenes or descriptions in your answer, just answer the question.
                DO NOT try to generalize or provide possible scenarios.
                ONLY use the information in the description of the images to answer the question.
                BE concise and specific.
            `
        ,
            question
    );
}