// Healthcheck initializes a fresh local replica set and waits for its primary.
// Existing data/configuration is retained; never reconfigure a running set.
try {
  const result = db.adminCommand({ hello: 1 });
  if (result.setName === "rs0" && result.isWritablePrimary) {
    quit(0);
  }
  if (!result.setName) {
    rs.initiate({ _id: "rs0", members: [{ _id: 0, host: "mongodb:27017" }] });
  }
  quit(1);
} catch (error) {
  // Election/startup retries belong to the container healthcheck, not a busy loop.
  quit(1);
}
