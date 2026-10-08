const assert=require('node:assert/strict');
const {navigate}=require('./e2e-navigation.cjs');
(async()=>{
 let calls=0;
 assert.equal(await navigate(async()=>{if(++calls===1)throw new Error('page.reload: net::ERR_NETWORK_CHANGED');return 200},{delayMs:0}),200);
 assert.equal(calls,2);
 calls=0;
 await assert.rejects(()=>navigate(async()=>{calls++;throw new Error('writeEmbed is not defined')},{delayMs:0}),/writeEmbed/);
 assert.equal(calls,1);
 calls=0;
 await assert.rejects(()=>navigate(async()=>{calls++;throw new Error('net::ERR_NETWORK_CHANGED')},{delayMs:0}),/ERR_NETWORK_CHANGED/);
 assert.equal(calls,2);
 calls=0;
 await assert.rejects(()=>navigate(async()=>{calls++;throw new Error('net::ERR_CONNECTION_REFUSED')},{delayMs:0}),/ERR_CONNECTION_REFUSED/);
 assert.equal(calls,1);
 console.log('Navigation retry tests: 4 passed; JavaScript and persistent failures remain failures');
})().catch(e=>{console.error(e);process.exit(1)});
