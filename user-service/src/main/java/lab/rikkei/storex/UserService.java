package lab.rikkei.storex;

import java.util.Map;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@SpringBootApplication
@RestController
public class UserService {
    private static final String SERVICE = "user-service";

    public static void main(String[] args) {
        SpringApplication.run(UserService.class, args);
    }

    @GetMapping("/")
    public Map<String, Object> index(HttpServletRequest request) {
        return Map.of("service", SERVICE, "receivedPath", request.getRequestURI());
    }

    @GetMapping("/123")
    public Map<String, Object> user(HttpServletRequest request) {
        return Map.of("service", SERVICE, "receivedPath", request.getRequestURI(),
                "userId", 123, "name", "Demo Shopper");
    }

    @GetMapping("/health")
    public Map<String, Object> health(HttpServletRequest request) {
        return Map.of("service", SERVICE, "receivedPath", request.getRequestURI(), "status", "UP");
    }
}
