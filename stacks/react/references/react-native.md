# React Native / Expo

Applies to React Native 0.76–0.88 and Expo SDK 52–58 with Expo Router. RN 0.82+ and Expo SDK 55+ run only on the New Architecture. The main skill's state, effect, hook, memoization, form and review rules still apply. Its DOM-only rules (`<div>`, `href`, browser storage, `NEXT_PUBLIC_*`) do not — there is no DOM, no URL bar and no browser fetch caching.

## Structure and navigation

- Route files under `app/` stay thin: read and validate params, then render a screen component from `features/` or `components/`.
- Validate `useLocalSearchParams()` with a schema before use — deep links and dynamic routes deliver untrusted strings.
- Expo SDK 56+: Expo Router no longer depends on React Navigation — never import from `@react-navigation/*` in an Expo Router app; migrate with the `sdk-56-expo-router-react-navigation-replace` codemod.

```tsx
const Params = z.object({ id: z.string().uuid() });
export default function UserRoute() {
  const parsed = Params.safeParse(useLocalSearchParams());
  if (!parsed.success) return <Redirect href="/not-found" />;
  return <UserProfile userId={parsed.data.id} />;
}
```

## State and data

- Each concern has one home: server data in TanStack Query (or SWR); UI state in `useState`, then Zustand/Jotai/Context when shared; navigation state in route params; forms in React Hook Form with a zod resolver; secrets in `expo-secure-store`; other persistence in AsyncStorage or MMKV.
- Parse API responses with zod inside `queryFn` and infer the type from the schema; invalidate the affected query keys in the mutation's `onSuccess`.
- Wire TanStack Query's `focusManager` to `AppState` and `onlineManager` to NetInfo — RN has no window focus or online events, so refetch-on-focus/reconnect is silently off otherwise.

## Lists

- Never `.map()` a dynamic array inside a `ScrollView` — no virtualization, high memory, jank. Use `FlatList`, or `FlashList` for large or heterogeneous lists.
- `keyExtractor` returns a stable id; `renderItem` is a stable reference (module-level or `useCallback`) that renders a `memo` row.
- Give fixed-height rows `getItemLayout`; tune `initialNumToRender`/`windowSize` only after profiling.
- Never nest a virtualized list inside a `ScrollView` with the same scroll direction — virtualization stops working. Use the list's `ListHeaderComponent`/`ListFooterComponent`.

## Rendering and styling

- Every string renders inside `<Text>`. A bare string in a `View` — including `{count && <Badge />}` when `count` is `0` — crashes on native. Use explicit ternaries.
- Use one styling system, the repo's: `StyleSheet.create` at module scope, or NativeWind `className`. No inline style objects in list rows or other hot paths.
- Use `react-native-safe-area-context` (`SafeAreaView`, `useSafeAreaInsets`), not the core `SafeAreaView` (iOS-only, deprecated).
- Animate with `react-native-reanimated` (runs on the UI thread) or `useNativeDriver: true`; never drive per-frame animation through React state on the JS thread.
- RN 0.87+ makes the Strict TypeScript API the default: never deep-import `react-native/Libraries/*` — it is a type error, and the opt-out ends after 0.88.
- Never use removed APIs: `InteractionManager` (use `requestIdleCallback`), the `Touchable` root export, `Modal` `animated`, `StatusBar` `backgroundColor`/`translucent` (0.87); `StyleSheet.absoluteFillObject` (0.85, use `absoluteFill`). `ImageBackground` is deprecated.

## Native APIs and security

- Wrap Expo SDK calls and subscriptions in `use*` hooks, never inline in JSX. Remove subscriptions in the effect cleanup and ignore async results that arrive after unmount.
- Model permission state explicitly (`loading | denied | granted`) and show an actionable message on denial — not a blank screen.
- Store tokens and secrets in `expo-secure-store` (Keychain/Keystore), never in AsyncStorage or MMKV (unencrypted).
- Never ship a private key in the app: `EXPO_PUBLIC_*` values and string constants are extractable from the binary. Privileged calls go through your backend; ship only public keys protected by backend rules.
- Validate push notification payloads like any external input.
- Before adding a native dependency, confirm it supports the New Architecture (React Native Directory lists this) — on RN 0.82+/SDK 55+ a legacy-only module cannot run.
- New audio/video code uses `expo-video`/`expo-audio`, never `expo-av` — it left Expo Go and stopped getting patches in SDK 55.
- Never start Metro with `--host 0.0.0.0` or keep `@react-native-community/cli` below 20 — Metro listens on all interfaces and its `/open-url` endpoint allowed OS command injection (CVE-2025-11953). Where upgrading is blocked, bind `--host 127.0.0.1`.

## Accessibility

- Interactive elements are `Pressable` (or `Button`) with `accessibilityRole`; icon-only controls also need `accessibilityLabel`.
- Error text uses `accessibilityRole="alert"`.
- Never set `allowFontScaling={false}` broadly — Dynamic Type users need it. Cap with `maxFontSizeMultiplier` where a layout breaks.
- Touch targets are at least 44×44 pt; use `hitSlop` for small icons.

## Testing

- Jest with the `jest-expo` preset (bare RN 0.85+: `@react-native/jest-preset`, no longer `react-native`) and React Native Testing Library, using its `userEvent` and role/label/text queries — the same rules as the main skill.
- RNTL 14 is async: `await render(...)`, and await `renderHook`, `act` and events; it drops React 18 and needs the `test-renderer` peer instead of `react-test-renderer`. Stay on RNTL 13 for React 18.
- Mock native modules at the module boundary (e.g. `jest.mock("expo-location")`) only where `jest-expo` doesn't already; never mock the component under test.
- Mock HTTP with MSW via `msw/node`. MSW 3 is ESM-only, so Jest must transform it (or stay on MSW 2); in-app mocking uses `@msw/react-native`, not `msw/native`.
- Device-level flows (navigation stacks, permission prompts, deep links) belong in a device E2E tool such as Detox, not in Jest.

## Review
Every rule above is also a review check.

## Verify

Prefer the repo's scripts. Fallbacks:

```bash
npx expo-doctor            # dependency and config health
npx expo install --check   # native package versions match the Expo SDK
npx tsc --noEmit
npx jest [path]
```
