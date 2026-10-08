// Retry only Chromium's explicit network-change navigation error, once.
async function navigate(operation, {delayMs=500}={}) {
  try { return await operation(); }
  catch(error) {
    if(!String(error?.message).includes('net::ERR_NETWORK_CHANGED'))throw error;
    console.warn('E2E navigation: network changed; retrying once');
    await new Promise(resolve=>setTimeout(resolve,delayMs));
    return operation();
  }
}
const goto=(page,...args)=>navigate(()=>page.goto(...args));
const reload=(page,...args)=>navigate(()=>page.reload(...args));
module.exports={navigate,goto,reload};
