/** Contract for a remote browser instance row, matching the panel table. */
export interface RemoteBrowserRow {
  browser: string;
  cdpUrl: string;
  live: boolean;
  profileId: string;
  agent: string;
  region: string;
  startedAt: string;
  duration: string;
  cost: string;
}
