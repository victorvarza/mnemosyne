/**
 * Example usage of the Mnemosyne OpenCode plugin
 */

// This is how you would use the plugin in an OpenCode session

// Example 1: The plugin automatically stores important information
// When you say: "Remember that I prefer Python for backend development"
// It automatically stores this as a memory

// Example 2: The plugin automatically retrieves relevant context
// When you ask: "What programming language should I use for this project?"
// It automatically includes relevant memories in the context

// Example 3: Scan source code for vulnerabilities
/*
> scan --projectPath ./my-web-app
*/

// Example 4: Perform pentest against deployed application
/*
> pentest --sourcePath ./my-web-app --targetUrl https://staging.myapp.com
*/

// Example 5: Manual memory storage (if needed)
/*
> remember --content "The application uses JWT tokens for authentication"
*/

// Example 6: Manual memory retrieval (if needed)
/*
> recall --query "authentication method" --topK 3
*/

console.log("Examples of using the Mnemosyne OpenCode plugin:");
console.log("1. Automatic memory storage from conversations");
console.log("2. Automatic context retrieval for AI responses");
console.log("3. Scan code for security issues with 'scan' command");
console.log("4. Perform authorized pentesting with 'pentest' command");
console.log("\nThe remember/recall functionality works automatically!");
console.log("Manual tools are available if you need explicit control.");