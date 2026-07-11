export function selectWebstorageFlag(allowedFlags = process.allowedNodeEnvironmentFlags) {
  if (allowedFlags.has('--no-webstorage')) {
    return '--no-webstorage';
  }
  if (allowedFlags.has('--no-experimental-webstorage')) {
    return '--no-experimental-webstorage';
  }
  return undefined;
}
