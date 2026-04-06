import {
  createContext,
  useContext,
  useState,
  useEffect,
  ReactNode,
} from "react";
import {
  loginUser,
  registerUser,
  getAuthToken,
  setAuthToken,
  clearAuthToken,
  getCurrentUser,
} from "@/lib/api";

interface User {
  id: string;
  email: string;
  full_name: string;
}

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (full_name: string, email: string, password: string) => Promise<void>;
  logout: () => void;
  isLoading: boolean;
  error: string | null;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Check for existing session on mount
  useEffect(() => {
    let isMounted = true;

    const initializeAuth = async () => {
      const url = new URL(window.location.href);
      const oauthToken = url.searchParams.get("token");
      const storedUser = localStorage.getItem("saifai-user");
      const token = oauthToken || getAuthToken();

      if (!token) {
        if (isMounted) {
          setIsLoading(false);
        }
        return;
      }

      try {
        if (oauthToken) {
          setAuthToken(oauthToken);
          localStorage.setItem("saifai-registered", "true");
        }

        if (storedUser && !oauthToken) {
          setUser(JSON.parse(storedUser));
        } else {
          const currentUser = await getCurrentUser(token);
          const userData: User = {
            id: currentUser.id,
            email: currentUser.email,
            full_name: currentUser.full_name,
          };

          localStorage.setItem("saifai-user", JSON.stringify(userData));
          if (isMounted) {
            setUser(userData);
          }
        }

        if (oauthToken) {
          url.searchParams.delete("token");
          window.history.replaceState({}, document.title, `${url.pathname}${url.search}${url.hash}`);
        }
      } catch (e) {
        localStorage.removeItem("saifai-user");
        clearAuthToken();
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    };

    void initializeAuth();

    return () => {
      isMounted = false;
    };
  }, []);

  const signup = async (full_name: string, email: string, password: string) => {
    setIsLoading(true);
    setError(null);

    try {
      await registerUser(email, password, full_name);
      localStorage.setItem("saifai-registered", "true");

      // Complete signup as an authenticated session so protected API calls
      // immediately have a bearer token available.
      const loginResponse = await loginUser(email, password);
      setAuthToken(loginResponse.access_token);

      const userData: User = {
        id: loginResponse.user.id,
        email: loginResponse.user.email,
        full_name: loginResponse.user.full_name,
      };

      localStorage.setItem("saifai-user", JSON.stringify(userData));
      setUser(userData);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Signup failed";
      setError(errorMessage);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const login = async (email: string, password: string) => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await loginUser(email, password);

      // Store token and user data
      setAuthToken(response.access_token);
      localStorage.setItem("saifai-registered", "true");

      const userData: User = {
        id: response.user.id,
        email: response.user.email,
        full_name: response.user.full_name,
      };

      localStorage.setItem("saifai-user", JSON.stringify(userData));
      setUser(userData);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Login failed";
      setError(errorMessage);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const logout = () => {
    localStorage.removeItem("saifai-user");
    clearAuthToken();
    setUser(null);
    setError(null);
  };

  const isAuthenticated = !!user && !!getAuthToken();

  const value = {
    user,
    isAuthenticated,
    login,
    signup,
    logout,
    isLoading,
    error,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
